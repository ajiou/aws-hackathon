import { useEffect, useId, useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, MapPin, Phone, School, Users, X } from "lucide-react";
import { usePark } from "../api/queries";
import { QueryState, TierBadge, ReasonList } from "./common";
import { Button } from "./ui/button";
import s from "../styles/App.module.css";

export function ParkDrawer({
  id,
  name,
  onClose,
}: {
  id: string;
  name?: string;
  onClose: () => void;
}) {
  const park = usePark(id, !!id);
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    heading.current?.closest("aside")?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [id]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        close.current();
        document
          .querySelector<HTMLSelectElement>("#map-park-select")
          ?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  return (
    <aside className={s.parkDrawer} aria-labelledby={titleId} data-park-drawer>
      <Button
        variant="ghost"
        size="icon"
        className="absolute right-3 top-3"
        aria-label="關閉園所資訊"
        onClick={() => {
          onClose();
          document
            .querySelector<HTMLSelectElement>("#map-park-select")
            ?.focus({ preventScroll: true });
        }}
      >
        <X aria-hidden="true" />
      </Button>
      <div className="space-y-2 pr-8">
        <span className="inline-flex size-10 items-center justify-center rounded-lg bg-accent text-primary">
          <School className="size-5" aria-hidden="true" />
        </span>
        <h2 id={titleId} ref={heading} tabIndex={-1}>
          {park.data?.name ?? name ?? "園所基本資料"}
        </h2>
        <p className="text-sm text-muted-foreground">園所基本資料與查核資訊</p>
      </div>
      <QueryState query={park}>
        {(p) => (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-primary">
                {p.institution_type}
              </span>
              <span className="text-sm text-muted-foreground">
                {p.town} · {p.is_active ? "營運中" : "已停辦"}
              </span>
              <TierBadge tier={p.risk.tier} />
            </div>
            <dl className="m-0 grid gap-4 rounded-lg bg-muted p-4 text-sm">
              <div className="grid grid-cols-[5rem_1fr] gap-3">
                <dt className="flex items-center gap-2 text-muted-foreground">
                  <MapPin className="size-4" aria-hidden="true" />
                  地址
                </dt>
                <dd className="m-0 break-words">{p.address || "未提供"}</dd>
              </div>
              <div className="grid grid-cols-[5rem_1fr] gap-3">
                <dt className="flex items-center gap-2 text-muted-foreground">
                  <Phone className="size-4" aria-hidden="true" />
                  電話
                </dt>
                <dd className="m-0">{p.tel || "未提供"}</dd>
              </div>
              <div className="grid grid-cols-[5rem_1fr] gap-3">
                <dt className="flex items-center gap-2 text-muted-foreground">
                  <Users className="size-4" aria-hidden="true" />
                  核定人數
                </dt>
                <dd className="m-0">
                  {p.count_approved === null
                    ? "未提供"
                    : `${p.count_approved} 人`}
                </dd>
              </div>
            </dl>
            <div>
              <h3 className="text-sm">查核參考</h3>
              <ReasonList reasons={p.reasons} />
            </div>
            <Button asChild>
              <Link to={`/park/${encodeURIComponent(p.park_id)}`}>
                查看完整園所分析
                <ArrowUpRight />
              </Link>
            </Button>
          </>
        )}
      </QueryState>
    </aside>
  );
}
