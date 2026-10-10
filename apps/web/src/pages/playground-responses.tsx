import { useState } from "react";
import { useModels } from "@/api/models";
import { type CreateResponse, useCreateResponse } from "@/api/responses";
import { type HistoryEntry, PlaygroundHistory } from "@/components/playground-history";
import {
  newMessage,
  type PlaygroundMessage,
  type ResponsesRole,
} from "@/components/playground-messages";
import type { OptionValues } from "@/components/playground-options";
import { ResponsesPlaygroundInput } from "@/components/responses-playground-input";
import {
  buildResponsesBody,
  ResponsesPlaygroundOptions,
} from "@/components/responses-playground-options";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useResponseStream } from "@/hooks/use-response-stream";

function previewOf(messages: readonly PlaygroundMessage<ResponsesRole>[]): string {
  const last = messages.at(-1);
  return last && last.content !== "" ? last.content : "(no text)";
}

type Result = { answer: string; error: string | null };

function outputTextOf(output: readonly unknown[]): string {
  const texts: string[] = [];
  for (const item of output) {
    if (typeof item !== "object" || item === null) continue;
    if (!("type" in item) || item.type !== "message") continue;
    if (!("content" in item) || !Array.isArray(item.content)) continue;
    for (const part of item.content) {
      if (
        typeof part === "object" &&
        part !== null &&
        "text" in part &&
        typeof part.text === "string"
      ) {
        texts.push(part.text);
      }
    }
  }
  return texts.length > 0 ? texts.join("\n\n") : JSON.stringify(output);
}

export function PlaygroundResponsesPage() {
  const models = useModels();
  const creation = useCreateResponse();
  const stream = useResponseStream();
  const [messages, setMessages] = useState<PlaygroundMessage<ResponsesRole>[]>(() => [
    newMessage("user"),
  ]);
  const [instructions, setInstructions] = useState("");
  const [chosenModel, setChosenModel] = useState<string | undefined>();
  const [values, setValues] = useState<OptionValues>({});
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const modelIds = models.data?.map((model) => model.id) ?? [];
  const model = chosenModel ?? modelIds[0];
  const busy = creation.isPending || stream.isStreaming;

  const record = (
    request: CreateResponse,
    status: HistoryEntry["status"],
    answer: string,
    error: string | null,
  ) => {
    setHistory((entries) => [
      ...entries,
      {
        id: crypto.randomUUID(),
        request,
        preview: previewOf(messages),
        status,
        answer,
        error,
      },
    ]);
    setResult({ answer, error });
  };

  const send = async () => {
    if (model === undefined) return;
    const built = buildResponsesBody(model, messages, instructions, values);
    if ("error" in built) {
      setFormError(built.error);
      return;
    }
    setFormError(null);
    setResult(null);
    const { body } = built;
    if (values.stream === "true") {
      const outcome = await stream.send(body);
      record(
        { ...body, stream: true },
        outcome.status,
        outcome.text,
        outcome.status === "failed" ? outcome.message : null,
      );
      return;
    }
    try {
      const response = await creation.mutateAsync(body);
      record(body, "completed", outputTextOf(response.output), null);
    } catch (caught) {
      record(
        body,
        "failed",
        "",
        caught instanceof Error ? caught.message : "Request failed",
      );
    }
  };

  const shown = stream.isStreaming ? { answer: stream.text, error: null } : result;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Request</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <ResponsesPlaygroundInput
              messages={messages}
              onMessagesChange={setMessages}
              instructions={instructions}
              onInstructionsChange={setInstructions}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                onClick={send}
                disabled={busy || model === undefined}
              >
                Send
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={stream.cancel}
                disabled={!stream.isStreaming}
              >
                Cancel
              </Button>
            </div>
            {formError && (
              <p role="alert" className="text-destructive text-sm">
                {formError}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Answer</CardTitle>
          </CardHeader>
          <CardContent aria-live="polite">
            {shown?.error ? (
              <p role="alert" className="text-destructive text-sm">
                {shown.error}
              </p>
            ) : (
              <p className="whitespace-pre-wrap text-sm">{shown?.answer}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>History</CardTitle>
          </CardHeader>
          <CardContent>
            <PlaygroundHistory
              entries={history}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </CardContent>
        </Card>
      </div>
      <Card className="self-start">
        <CardHeader>
          <CardTitle>Options</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsesPlaygroundOptions
            models={modelIds}
            model={model}
            onModelChange={setChosenModel}
            values={values}
            onValuesChange={setValues}
          />
        </CardContent>
      </Card>
    </div>
  );
}
