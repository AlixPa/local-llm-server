import type { Participant, WorkflowStepItem } from "@/api/observability";

export type Lane = 0 | 1 | 2;

export const LANE: Record<Participant, Lane> = { client: 0, api: 1, ollama: 2 };

export type StepLayout = {
  step: WorkflowStepItem;
  fromLane: Lane;
  toLane: Lane;
  direction: "right" | "left";
  failed: boolean;
  inProgress: boolean;
  canceled: boolean;
  interrupted: boolean;
};

export function layoutSteps(steps: WorkflowStepItem[]): StepLayout[] {
  return steps.map((step) => {
    const fromLane = LANE[step.source];
    const toLane = LANE[step.destination];
    return {
      step,
      fromLane,
      toLane,
      direction: toLane > fromLane ? "right" : "left",
      failed: step.status === "failed",
      inProgress: step.status === "in_progress",
      canceled: step.status === "canceled",
      interrupted: step.status === "interrupted",
    };
  });
}
