import {
  type PlaygroundMessage,
  PlaygroundMessages,
  RESPONSES_ROLES,
  type ResponsesRole,
} from "@/components/playground-messages";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Props = {
  messages: PlaygroundMessage<ResponsesRole>[];
  onMessagesChange: (messages: PlaygroundMessage<ResponsesRole>[]) => void;
  instructions: string;
  onInstructionsChange: (instructions: string) => void;
};

export function ResponsesPlaygroundInput({
  messages,
  onMessagesChange,
  instructions,
  onInstructionsChange,
}: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="responses-instructions">Instructions</Label>
        <Textarea
          id="responses-instructions"
          value={instructions}
          placeholder="Optional system-level instructions"
          onChange={(event) => onInstructionsChange(event.target.value)}
        />
      </div>
      <PlaygroundMessages
        messages={messages}
        onChange={onMessagesChange}
        roles={RESPONSES_ROLES}
        defaultRole="user"
      />
    </div>
  );
}
