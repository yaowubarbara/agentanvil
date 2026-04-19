"use client";
import { useEffect, useRef, useState } from "react";

type Props = {
  totalSteps: number;
  onStepChange: (step: number) => void;
  initialStep?: number;
};

const SPEEDS = [0.5, 1, 2, 4];

export default function PlaybackControls({
  totalSteps,
  onStepChange,
  initialStep = 0,
}: Props) {
  const [step, setStep] = useState(initialStep);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    onStepChange(step);
  }, [step, onStepChange]);

  useEffect(() => {
    if (!playing) {
      if (timer.current) clearTimeout(timer.current);
      return;
    }
    if (step >= totalSteps - 1) {
      setPlaying(false);
      return;
    }
    timer.current = setTimeout(() => {
      setStep((s) => Math.min(s + 1, totalSteps - 1));
    }, 800 / speed);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [playing, step, totalSteps, speed]);

  return (
    <div className="playback">
      <button
        className="pb-btn pb-primary"
        onClick={() => {
          if (step >= totalSteps - 1) setStep(0);
          setPlaying((p) => !p);
        }}
      >
        {playing ? "⏸" : "▶"} {playing ? "Pause" : "Play"}
      </button>
      <button
        className="pb-btn"
        onClick={() => {
          setPlaying(false);
          setStep(0);
        }}
      >
        ⏮ Reset
      </button>
      <button
        className="pb-btn"
        onClick={() => setStep((s) => Math.max(0, s - 1))}
      >
        ⏪ Prev
      </button>
      <button
        className="pb-btn"
        onClick={() =>
          setStep((s) => Math.min(totalSteps - 1, s + 1))
        }
      >
        ⏩ Next
      </button>
      <input
        type="range"
        min={0}
        max={Math.max(0, totalSteps - 1)}
        value={step}
        onChange={(e) => {
          setPlaying(false);
          setStep(Number(e.target.value));
        }}
        className="pb-scrub"
      />
      <div className="pb-step-label">
        step {step + 1} / {totalSteps}
      </div>
      <div className="pb-speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            className={`pb-speed-btn ${speed === s ? "on" : ""}`}
            onClick={() => setSpeed(s)}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}
