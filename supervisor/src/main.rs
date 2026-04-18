//! AgentAnvil supervisor: narrow-scope process supervisor.
//!
//! Exactly three capabilities, in order of execution:
//!   1. Spawn a Unix-socket listener for Python heartbeat messages.
//!   2. Spawn the child process, exporting AGENTANVIL_SUPER_SOCK.
//!   3. Poll /proc for peak RSS; enforce wall-clock timeout with
//!      SIGTERM then SIGKILL escalation.
//!
//! Anything more sophisticated (seccomp, namespaces, cgroup enforcement)
//! is explicitly out of scope — see README for rationale.

use clap::{Parser, Subcommand};
use nix::sys::signal::{self, Signal};
use nix::unistd::Pid;
use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::process::{Command, ExitCode, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Parser, Debug)]
#[command(name = "agentanvil-supervisor", version, about)]
struct Cli {
    #[command(subcommand)]
    cmd: SubCmd,
}

#[derive(Subcommand, Debug)]
enum SubCmd {
    /// Supervise a child process with timeout + RSS monitoring + heartbeat socket.
    Run(RunArgs),
}

#[derive(Parser, Debug)]
struct RunArgs {
    /// Wall-clock timeout in seconds. SIGTERM sent when exceeded.
    #[arg(long, default_value_t = 300)]
    timeout: u64,
    /// Grace period after SIGTERM before SIGKILL, in seconds.
    #[arg(long, default_value_t = 10)]
    grace: u64,
    /// Unix socket path for heartbeats from the child.
    #[arg(long, default_value = "/tmp/agentanvil-supervisor.sock")]
    socket: PathBuf,
    /// Polling interval for /proc/<pid>/status in milliseconds.
    #[arg(long, default_value_t = 200)]
    poll_ms: u64,
    /// The command to run, after `--`.
    #[arg(trailing_var_arg = true, required = true)]
    command: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "type", rename_all = "snake_case")]
enum Heartbeat {
    Start {
        trajectory_id: Option<String>,
        pid: Option<u32>,
    },
    Progress {
        step: u32,
        note: Option<String>,
    },
    Finish {
        ok: bool,
        final_answer: Option<String>,
    },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum TerminationReason {
    Completed,
    TimeoutSigterm,
    TimeoutSigkill,
    SupervisorError { message: String },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct FinalReport {
    ok: bool,
    exit_code: Option<i32>,
    signaled: Option<i32>,
    duration_ms: u128,
    rss_peak_kb: Option<u64>,
    termination_reason: TerminationReason,
    heartbeats: Vec<Heartbeat>,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.cmd {
        SubCmd::Run(args) => match run(args) {
            Ok(code) => ExitCode::from(code as u8),
            Err(e) => {
                eprintln!("supervisor error: {}", e);
                ExitCode::from(1)
            }
        },
    }
}

fn run(args: RunArgs) -> Result<i32, String> {
    let start = Instant::now();

    let heartbeats = Arc::new(Mutex::new(Vec::<Heartbeat>::new()));
    let (stop_tx, stop_rx) = mpsc::channel::<()>();
    let socket_path = args.socket.clone();
    let listener_handle = spawn_socket_listener(
        socket_path.clone(),
        Arc::clone(&heartbeats),
        stop_rx,
    )?;

    let mut cmd_iter = args.command.iter();
    let program = cmd_iter.next().ok_or("empty command")?;
    let cmd_args: Vec<&String> = cmd_iter.collect();

    let mut child = Command::new(program)
        .args(&cmd_args)
        .env("AGENTANVIL_SUPER_SOCK", &socket_path)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn child: {}", e))?;

    let child_pid = child.id();
    let mut peak_rss_kb: Option<u64> = None;
    let mut escalation_at: Option<Instant> = None;
    let mut termination = TerminationReason::Completed;

    let exit_status = loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|e| format!("try_wait failed: {}", e))?
        {
            break status;
        }

        if let Some(rss) = read_rss_kb(child_pid) {
            peak_rss_kb = Some(peak_rss_kb.map_or(rss, |p| p.max(rss)));
        }

        let elapsed = start.elapsed();
        if elapsed > Duration::from_secs(args.timeout) {
            match escalation_at {
                None => {
                    let _ = signal::kill(Pid::from_raw(child_pid as i32), Signal::SIGTERM);
                    escalation_at = Some(Instant::now());
                    termination = TerminationReason::TimeoutSigterm;
                }
                Some(t) if t.elapsed() > Duration::from_secs(args.grace) => {
                    let _ = signal::kill(Pid::from_raw(child_pid as i32), Signal::SIGKILL);
                    termination = TerminationReason::TimeoutSigkill;
                }
                _ => {}
            }
        }

        thread::sleep(Duration::from_millis(args.poll_ms));
    };

    let _ = stop_tx.send(());
    let _ = std::fs::remove_file(&args.socket);
    let _ = listener_handle.join();

    let duration_ms = start.elapsed().as_millis();
    #[cfg(unix)]
    let signaled = {
        use std::os::unix::process::ExitStatusExt;
        exit_status.signal()
    };
    #[cfg(not(unix))]
    let signaled: Option<i32> = None;

    let exit_code = exit_status.code();
    let ok = matches!(termination, TerminationReason::Completed)
        && exit_status.success();

    let hb_snapshot = heartbeats
        .lock()
        .map_err(|e| format!("heartbeats lock poisoned: {}", e))?
        .clone();

    let report = FinalReport {
        ok,
        exit_code,
        signaled,
        duration_ms,
        rss_peak_kb: peak_rss_kb,
        termination_reason: termination,
        heartbeats: hb_snapshot,
    };
    let report_line = serde_json::to_string(&report)
        .map_err(|e| format!("failed to serialize final report: {}", e))?;
    eprintln!("ANVIL_REPORT: {}", report_line);

    Ok(exit_code.unwrap_or(if signaled.is_some() { 128 + signaled.unwrap() } else { 1 }))
}

fn spawn_socket_listener(
    path: PathBuf,
    sink: Arc<Mutex<Vec<Heartbeat>>>,
    stop_rx: mpsc::Receiver<()>,
) -> Result<thread::JoinHandle<()>, String> {
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path)
        .map_err(|e| format!("socket bind {:?} failed: {}", path, e))?;
    listener
        .set_nonblocking(true)
        .map_err(|e| format!("set_nonblocking: {}", e))?;

    Ok(thread::spawn(move || {
        loop {
            if stop_rx.try_recv().is_ok() {
                return;
            }
            match listener.accept() {
                Ok((stream, _)) => {
                    let sink = Arc::clone(&sink);
                    thread::spawn(move || {
                        let reader = BufReader::new(stream);
                        for line in reader.lines().flatten() {
                            if let Ok(hb) = serde_json::from_str::<Heartbeat>(&line) {
                                if let Ok(mut v) = sink.lock() {
                                    v.push(hb);
                                }
                            }
                        }
                    });
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(50));
                }
                Err(_) => return,
            }
        }
    }))
}

fn read_rss_kb(pid: u32) -> Option<u64> {
    let content = std::fs::read_to_string(format!("/proc/{}/status", pid)).ok()?;
    for line in content.lines() {
        if let Some(rest) = line.strip_prefix("VmRSS:") {
            let first = rest.trim().split_whitespace().next()?;
            return first.parse::<u64>().ok();
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heartbeat_json_roundtrip() {
        let hb = Heartbeat::Progress {
            step: 3,
            note: Some("tool_call".to_string()),
        };
        let s = serde_json::to_string(&hb).unwrap();
        let back: Heartbeat = serde_json::from_str(&s).unwrap();
        match back {
            Heartbeat::Progress { step, note } => {
                assert_eq!(step, 3);
                assert_eq!(note.as_deref(), Some("tool_call"));
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn report_shape() {
        let r = FinalReport {
            ok: true,
            exit_code: Some(0),
            signaled: None,
            duration_ms: 123,
            rss_peak_kb: Some(456),
            termination_reason: TerminationReason::Completed,
            heartbeats: vec![],
        };
        let s = serde_json::to_string(&r).unwrap();
        assert!(s.contains("\"ok\":true"));
        assert!(s.contains("\"termination_reason\":{\"kind\":\"completed\"}"));
    }
}
