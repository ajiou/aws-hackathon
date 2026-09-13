import { useEffect, useRef, useState } from "react";
import { Link, matchPath, useLocation } from "react-router-dom";
import { Bot, Send, X, TriangleAlert } from "lucide-react";
import { ApiError, postChat } from "../api/client";
import { usePark } from "../api/queries";
import type { ChatPark, ChatResponse } from "../api/types";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; reply: ChatResponse; question: string }
  | { role: "error"; text: string };

// 目前畫面正在看的園所：單園頁 /park/:id，或地圖上選取的 ?selected=。
function useContextParkId() {
  const location = useLocation();
  const detail = matchPath("/park/:id", location.pathname)?.params.id;
  if (detail) return decodeURIComponent(detail);
  if (["/", "/map"].includes(location.pathname))
    return new URLSearchParams(location.search).get("selected") ?? "";
  return "";
}

// 模型常省略「新北市私立」等前綴，所以全名與簡稱都要能對到。
const shortName = (name: string) =>
  name.replace(/^新北市(市立|私立|立)?|^(私立|市立)/, "");
const escapeRegExp = (text: string) =>
  text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 把回答中出現的園名換成連結，點了直接進單園頁。
function linkParks(line: string, parks: ChatPark[]) {
  const byName = new Map<string, ChatPark>();
  for (const p of parks) {
    byName.set(p.name, p);
    if (shortName(p.name).length >= 4) byName.set(shortName(p.name), p);
  }
  if (!byName.size) return line;
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${names.map(escapeRegExp).join("|")})`);
  return line.split(pattern).map((piece, i) => {
    const park = byName.get(piece);
    return park ? (
      <Link
        key={i}
        to={`/park/${encodeURIComponent(park.park_id)}`}
        className="font-medium text-primary underline underline-offset-2"
      >
        {piece}
      </Link>
    ) : (
      piece
    );
  });
}

// LLM 回答是輕量 Markdown；只處理條列與粗體，其餘當純文字，避免注入 HTML。
function AnswerText({ text, parks }: { text: string; parks: ChatPark[] }) {
  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {text.split("\n").map((raw, i) => {
        const line = raw.replace(/\*\*/g, "").replace(/^#+\s*/, "");
        if (!line.trim()) return <div key={i} className="h-2" />;
        const bullet = /^\s*[-•*]\s+/.test(line);
        const body = bullet ? line.replace(/^\s*[-•*]\s+/, "") : line;
        return (
          <p key={i} className={cn(bullet && "pl-4 -indent-3")}>
            {bullet && "• "}
            {linkParks(body, parks)}
          </p>
        );
      })}
    </div>
  );
}

function ParkChip({ park }: { park: ChatPark }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      {park.name}
      {park.tier && ` · ${park.tier}風險`}
      {park.rank && ` · 第 ${park.rank} 名`}
      {!park.is_active && " · 已停辦"}
    </span>
  );
}

function AssistantReply({
  reply,
  onPick,
  disabled,
}: {
  reply: ChatResponse;
  onPick: (park: ChatPark) => void;
  disabled: boolean;
}) {
  return (
    <div className="space-y-2">
      {reply.park && <ParkChip park={reply.park} />}
      <AnswerText
        text={reply.answer}
        parks={[...reply.parks, ...(reply.park ? [reply.park] : [])]}
      />
      {reply.candidates.length > 0 && (
        <ul className="list-none space-y-1 pl-0" aria-label="相符的園所">
          {reply.candidates.map((p) => (
            <li key={p.park_id}>
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-start"
                disabled={disabled}
                onClick={() => onPick(p)}
              >
                {p.name}（{p.town}
                {p.tier ? `・${p.tier}風險` : ""}）
              </Button>
            </li>
          ))}
        </ul>
      )}
      {reply.source === "llm" && !reply.laws_enabled && (
        <p className="text-xs text-muted-foreground">
          法規知識庫尚未啟用：此回答只根據園況資料，未附法規依據。
        </p>
      )}
      {reply.source === "fallback" && (
        <p className="text-xs text-muted-foreground">
          此回答由系統模板產生，未經 AI 與法規檢索。
        </p>
      )}
      {reply.unverified_refs.length > 0 && (
        <p className="flex gap-1 text-xs text-[var(--c-tier-中)]">
          <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
          以下引用不在檢索到的條文中，請自行查證：
          {reply.unverified_refs.join("、")}
        </p>
      )}
      {reply.citations.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            參考條文 {reply.citations.length} 則
          </summary>
          <ul className="mt-1 list-none space-y-2 pl-0">
            {reply.citations.map((c, i) => (
              <li key={i} className="rounded border border-border p-2">
                <div className="font-medium">
                  {c.url ? (
                    <a href={c.url} target="_blank" rel="noreferrer">
                      《{c.law}》{c.article}
                    </a>
                  ) : (
                    `《${c.law}》${c.article}`
                  )}
                </div>
                <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                  {c.snippet.replace(/^《[^》]+》[^\n]*\n/, "")}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState(false);
  const [unbound, setUnbound] = useState(false);
  const contextId = useContextParkId();
  const contextPark = usePark(contextId, Boolean(contextId));
  const boundId = contextId && !unbound ? contextId : "";
  const listRef = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => setUnbound(false), [contextId]);
  useEffect(() => {
    if (listRef.current)
      listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, pending]);
  useEffect(() => () => controller.current?.abort(), []);

  async function ask(question: string, parkId?: string) {
    const message = question.trim();
    if (!message || pending) return;
    setMessages((m) => [...m, { role: "user", text: message }]);
    setDraft("");
    setPending(true);
    controller.current = new AbortController();
    try {
      const reply = await postChat(
        { message, ...(parkId ? { park_id: parkId } : {}) },
        controller.current.signal,
      );
      setMessages((m) => [
        ...m,
        { role: "assistant", reply, question: message },
      ]);
    } catch (error) {
      if (controller.current?.signal.aborted) return;
      const text =
        error instanceof ApiError
          ? `${error.message}${error.requestId !== "未提供" ? `（${error.requestId}）` : ""}`
          : "助理暫時無法回答，請稍後再試";
      setMessages((m) => [...m, { role: "error", text }]);
    } finally {
      setPending(false);
    }
  }

  if (!open)
    return (
      <Button
        className="no-print fixed right-4 bottom-4 z-50 h-12 rounded-full px-5 shadow-lg"
        onClick={() => setOpen(true)}
      >
        <Bot aria-hidden="true" />
        稽查助手
      </Button>
    );

  return (
    <section
      role="dialog"
      aria-label="稽查 AI 助手"
      className="no-print fixed right-4 bottom-4 z-50 flex h-[min(640px,calc(100vh-2rem))] w-[min(420px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
          <Bot className="size-5 text-primary" aria-hidden="true" />
          稽查 AI 助手
        </h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="關閉稽查助手"
          onClick={() => setOpen(false)}
        >
          <X />
        </Button>
      </header>

      <div
        ref={listRef}
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
        aria-live="polite"
      >
        {messages.length === 0 && (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>可以直接問園所狀況或法規，例如：</p>
            {[
              boundId && contextPark.data
                ? `${contextPark.data.name}最近狀況如何？要查什麼？`
                : "某某幼兒園最近狀況如何？",
              "這週應該優先查哪幾間？",
              "幼兒園超收會被怎麼罰？",
            ].map((example) => (
              <button
                key={example}
                type="button"
                className="block w-full rounded-md border border-border px-3 py-2 text-left hover:bg-muted"
                onClick={() => setDraft(example)}
              >
                {example}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <p
              key={i}
              className="ml-8 rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground"
            >
              {m.text}
            </p>
          ) : m.role === "error" ? (
            <p
              key={i}
              role="alert"
              className="mr-8 rounded-lg border border-[var(--c-tier-高-border)] bg-[var(--c-tier-高-bg)] px-3 py-2 text-sm text-[var(--c-tier-高)]"
            >
              {m.text}
            </p>
          ) : (
            <div key={i} className="mr-4 rounded-lg bg-muted/60 px-3 py-2">
              <AssistantReply
                reply={m.reply}
                disabled={pending}
                onPick={(park) => ask(m.question, park.park_id)}
              />
            </div>
          ),
        )}
        {pending && (
          <p className="text-sm text-muted-foreground">
            正在查詢園況與法規（約 5–15 秒）…
          </p>
        )}
      </div>

      <form
        className="space-y-2 border-t border-border px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(draft, boundId || undefined);
        }}
      >
        {boundId && contextPark.data && (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs text-primary">
            針對：{contextPark.data.name}
            <button
              type="button"
              aria-label="不針對此園所提問"
              className="rounded-full border-0 bg-transparent p-0 hover:bg-background"
              onClick={() => setUnbound(true)}
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          </span>
        )}
        <div className="flex items-end gap-2">
          <textarea
            aria-label="輸入問題"
            className="min-h-10 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm"
            rows={2}
            maxLength={500}
            placeholder="輸入園所名稱或法規問題"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                ask(draft, boundId || undefined);
              }
            }}
          />
          <Button
            type="submit"
            size="icon"
            aria-label="送出"
            disabled={pending || !draft.trim()}
          >
            <Send />
          </Button>
        </div>
        <p className="m-0 text-[11px] text-muted-foreground">
          僅供稽查排序參考，非違規認定；請勿輸入個人姓名。
        </p>
      </form>
    </section>
  );
}
