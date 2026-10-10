import { useState } from "react";
import { type CreateChatCompletionRequest, useCreateChatCompletion } from "@/api/chat";
import { useModels } from "@/api/models";
import { type HistoryEntry, PlaygroundHistory } from "@/components/playground-history";
import {
  newMessage,
  type PlaygroundMessage,
  PlaygroundMessages,
} from "@/components/playground-messages";
import {
  buildRequestBody,
  type OptionValues,
  PlaygroundOptions,
} from "@/components/playground-options";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChatStream } from "@/hooks/use-chat-stream";

function previewOf(request: CreateChatCompletionRequest): string {
  const last = request.messages.at(-1);
  return last && typeof last.content === "string" ? last.content : "(no text)";
}

type Result = { answer: string; error: string | null };

export function PlaygroundChatPage() {
  const models = useModels();
  const completion = useCreateChatCompletion();
  const stream = useChatStream();
  const [messages, setMessages] = useState<PlaygroundMessage[]>(() => [newMessage()]);
  const [chosenModel, setChosenModel] = useState<string | undefined>();
  const [values, setValues] = useState<OptionValues>({});
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const modelIds = models.data?.map((model) => model.id) ?? [];
  const model = chosenModel ?? modelIds[0];
  const busy = completion.isPending || stream.isStreaming;

  const record = (
    request: CreateChatCompletionRequest,
    status: HistoryEntry["status"],
    answer: string,
    error: string | null,
  ) => {
    setHistory((entries) => [
      ...entries,
      {
        id: crypto.randomUUID(),
        request,
        preview: previewOf(request),
        status,
        answer,
        error,
      },
    ]);
    setResult({ answer, error });
  };

  const send = async () => {
    if (model === undefined) return;
    const built = buildRequestBody(model, messages, values);
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
      const response = await completion.mutateAsync(body);
      const answer = response.choices
        .map((choice) => choice.message.content ?? JSON.stringify(choice.message))
        .join("\n\n");
      record(body, "completed", answer, null);
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
    <div className="grid gap-4 p-4 lg:grid-cols-[1fr_20rem]">
      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Conversation</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <PlaygroundMessages messages={messages} onChange={setMessages} />
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
          <PlaygroundOptions
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
