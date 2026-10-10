import { PlusIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export const CHAT_ROLES = ["system", "user", "assistant"] as const;
export const RESPONSES_ROLES = ["user", "assistant", "developer"] as const;
export type ChatRole = (typeof CHAT_ROLES)[number];
export type ResponsesRole = (typeof RESPONSES_ROLES)[number];
export type PlaygroundMessage<R extends string = ChatRole> = {
  id: string;
  role: R;
  content: string;
};

export function newMessage<R extends string>(role: R): PlaygroundMessage<R> {
  return { id: crypto.randomUUID(), role, content: "" };
}

type Props<R extends string> = {
  messages: PlaygroundMessage<R>[];
  onChange: (messages: PlaygroundMessage<R>[]) => void;
  roles: readonly R[];
  defaultRole: R;
};

export function PlaygroundMessages<R extends string>({
  messages,
  onChange,
  roles,
  defaultRole,
}: Props<R>) {
  const isRole = (value: string | null): value is R =>
    roles.some((role) => role === value);
  const update = (id: string, patch: Partial<PlaygroundMessage<R>>) =>
    onChange(
      messages.map((message) =>
        message.id === id ? { ...message, ...patch } : message,
      ),
    );

  return (
    <div className="flex flex-col gap-3">
      {messages.map((message, index) => (
        <div key={message.id} className="flex flex-col gap-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor={`message-${message.id}`}>Message {index + 1}</Label>
            <div className="flex items-center gap-2">
              <Select
                value={message.role}
                onValueChange={(role) => {
                  if (isRole(role)) update(message.id, { role });
                }}
              >
                <SelectTrigger aria-label={`Role of message ${index + 1}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role} value={role}>
                      {role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove message ${index + 1}`}
                disabled={messages.length === 1}
                onClick={() => onChange(messages.filter((m) => m.id !== message.id))}
              >
                <Trash2Icon />
              </Button>
            </div>
          </div>
          <Textarea
            id={`message-${message.id}`}
            value={message.content}
            onChange={(event) => update(message.id, { content: event.target.value })}
          />
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        className="self-start"
        onClick={() => onChange([...messages, newMessage(defaultRole)])}
      >
        <PlusIcon /> Add message
      </Button>
    </div>
  );
}
