import { useEffect, useRef } from "react";
import type { Conversation, Message as MessageT } from "../types";
import Message from "./Message";
import Composer from "./Composer";

interface Props {
  conversation: Conversation | null;
  messages: MessageT[];
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onClear: (id: string) => void;
}

export default function ChatView({
  conversation,
  messages,
  streaming,
  onSend,
  onStop,
  onClear,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!conversation) {
    return (
      <div className="flex flex-1 items-center justify-center text-neutral-500">
        <div className="text-center">
          <p className="text-lg font-medium text-neutral-300">
            Gemini Interactions Chat
          </p>
          <p className="mt-1 text-sm">
            Start a new chat or select a conversation.
          </p>
        </div>
      </div>
    );
  }

  const target =
    conversation.agent
      ? conversation.agent.split("/").pop()
      : conversation.model;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-5 py-3">
        <h1 className="truncate text-sm font-medium text-neutral-100">
          {conversation.title}
        </h1>
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              onClick={() => {
                if (confirm("Are you sure you want to clear the message history for this chat?")) {
                  onClear(conversation.id);
                }
              }}
              disabled={streaming}
              className="rounded border border-red-900 bg-red-950/40 px-2.5 py-1 text-xs font-medium text-red-400 transition hover:bg-red-950 disabled:opacity-50"
              title="Clear history"
            >
              Clear Chat
            </button>
          )}
          <span className="rounded-full bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300">
            {conversation.agent ? "agent" : "model"}: {target}
          </span>
        </div>
      </header>


      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.length === 0 && (
            <p className="py-12 text-center text-sm text-neutral-500">
              No messages yet. Say hello!
            </p>
          )}
          {messages.map((m) => (
            <Message key={m.id} message={m} />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      <Composer
        onSend={onSend}
        onStop={onStop}
        streaming={streaming}
        placeholder="Send a message…"
      />
    </div>
  );
}
