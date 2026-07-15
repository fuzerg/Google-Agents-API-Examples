import { useEffect, useRef } from "react";
import type { Conversation, Message as MessageT } from "../types";
import Message from "./Message";
import Composer from "./Composer";

interface AgentEvent {
  event_type: string;
  data?: any;
  detail?: string;
  timestamp: string;
}

interface Props {
  conversation: Conversation | null;
  messages: MessageT[];
  streaming: boolean;
  agentEvents?: AgentEvent[];
  onSend: (text: string) => void;
  onStop: () => void;
}

export default function ChatView({
  conversation,
  messages,
  streaming,
  agentEvents = [],
  onSend,
  onStop,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, agentEvents]);

  useEffect(() => {
    if (streaming) {
      eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [agentEvents, streaming]);

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
        <span className="rounded-full bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300">
          {conversation.agent ? "agent" : "model"}: {target}
        </span>
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
          {streaming && agentEvents.length > 0 && (
            <div className="flex justify-start">
              <div className="flex w-full max-w-[80%] flex-col gap-2 rounded-2xl bg-neutral-900 border border-neutral-800 p-4 text-xs">
                <div className="flex items-center justify-between border-b border-neutral-800 pb-1.5 mb-1 text-neutral-400 font-semibold">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 animate-ping rounded-full bg-blue-500" />
                    Agent Intermediate Events
                  </span>
                  <span>{agentEvents.length} events</span>
                </div>
                <div className="max-h-[160px] overflow-y-auto pr-1 flex flex-col gap-2.5 font-mono">
                  {agentEvents.map((ev, i) => (
                    <div key={i} className="flex flex-col gap-0.5 border-l-2 border-neutral-800 pl-2">
                      <div className="flex items-center justify-between text-[10px] text-neutral-500">
                        <span className="text-blue-400 font-bold">{ev.event_type}</span>
                        <span>{ev.timestamp}</span>
                      </div>
                      <div className="whitespace-pre-wrap text-neutral-300 break-all leading-relaxed">
                        {ev.data ? JSON.stringify(ev.data, null, 2) : ev.detail}
                      </div>
                    </div>
                  ))}
                  <div ref={eventsEndRef} />
                </div>
              </div>
            </div>
          )}
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
