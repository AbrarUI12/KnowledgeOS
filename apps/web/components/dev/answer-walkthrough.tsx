"use client";

import { useEffect, useRef, useState } from "react";

const examples = {
  supported: {
    label: "Supported answer",
    question: "How much parental leave do I get?",
    text: "Eligible employees receive 16 weeks of paid parental leave. Request it at least 30 days before your expected start date. [S1] Send the proposed dates to your manager and People Operations. [S2]",
    status: "Supported by two sample sources",
  },
  abstain: {
    label: "Insufficient evidence",
    question: "Does the policy cover contractors in every country?",
    text: "I cannot establish that from the available passages. They describe eligible employees, but do not define contractor eligibility or country-specific rules. Ask People Operations for the applicable policy.",
    status: "Abstained · insufficient evidence",
  },
  conflict: {
    label: "Conflicting policies",
    question: "HR-142-B: did parental leave change from 2025 to 2026?",
    text: "The 2025 handbook says 12 weeks [S4], while the 2026 handbook says 16 weeks [S1]. These passages disagree. The newer document suggests a change, but the samples do not establish the effective date or which policy applies to your request. Confirm with People Operations.",
    status: "Conflict detected · HR-142-B",
  },
};
type Example = keyof typeof examples;

export function AnswerWalkthrough({ inspect }: { inspect: (source: "S1" | "S2" | "S4") => void }) {
  const [example, setExample] = useState<Example>("supported");
  const [answer, setAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const current = examples[example];
  function stop() {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }
  useEffect(
    () => () => {
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );
  function run() {
    stop();
    const words = current.text.split(" ");
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setAnswer(current.text);
      setRunning(false);
      return;
    }
    setAnswer("");
    setRunning(true);
    let count = 0;
    timer.current = setInterval(() => {
      count += 1;
      setAnswer(words.slice(0, count).join(" "));
      if (count >= words.length) {
        stop();
        setRunning(false);
      }
    }, 45);
  }
  return (
    <div className="mt-8 border-t border-line pt-6">
      <h3 className="mb-3 text-lg font-semibold">Explore evidence outcomes</h3>
      <p className="mb-4 text-sm text-ink-secondary">
        Simulated word-by-word streaming. Reduced-motion preference shows the complete answer
        immediately.
      </p>
      <div className="mb-5 flex flex-wrap gap-2">
        {(Object.keys(examples) as Example[]).map((key) => (
          <button
            key={key}
            aria-pressed={example === key}
            className="rounded-control border border-control-border px-3 py-2 text-sm aria-pressed:bg-accent-soft aria-pressed:text-accent"
            onClick={() => {
              stop();
              setExample(key);
              setAnswer("");
              setRunning(false);
            }}
          >
            {examples[key].label}
          </button>
        ))}
      </div>
      <p className="mb-4 font-medium">{current.question}</p>
      <div className="flex gap-3">
        <button
          disabled={running}
          onClick={run}
          className="rounded-control bg-accent px-4 py-2 text-on-accent disabled:opacity-50"
        >
          Play outcome
        </button>
        {running && (
          <button
            onClick={() => {
              stop();
              setRunning(false);
            }}
            className="rounded-control border border-control-border px-3 py-2"
          >
            Stop
          </button>
        )}
      </div>
      <p role="status" className="mt-4 text-sm text-ink-secondary">
        {running
          ? "Streaming sample answer…"
          : answer
            ? current.status
            : "Choose an example, then play its answer."}
      </p>
      {answer && (
        <>
          <p aria-label="Sample answer" className="mt-4 whitespace-pre-wrap leading-7">
            {answer}
          </p>
          {!running && example !== "abstain" && (
            <div className="mt-4 flex flex-wrap gap-2">
              {(example === "conflict" ? ["S4", "S1"] : ["S1", "S2"]).map((source) => (
                <button
                  key={source}
                  onClick={() => inspect(source as "S1" | "S2" | "S4")}
                  className="rounded-control bg-accent-soft px-3 py-2 text-sm text-accent"
                >
                  Inspect [{source}]
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
