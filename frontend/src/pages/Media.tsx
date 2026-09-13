import { Link } from "react-router-dom";
import { useApi } from "../api/queries";
import { mediaPageSchema, type MediaPark } from "../api/types";
import {
  PageHeader,
  QueryState,
  TierBadge,
  CopyLink,
} from "../components/common";
import { EmptyState } from "../components/FilterBar";
import { MEDIA_TAB } from "./ParkDetail";
import s from "../styles/App.module.css";

/** 觀察窗固定 12 個月。分數那條路守著切點（2025-01-01），這一頁刻意不守——
 *  稽查人員要看的恰恰是切點之後的事。12 個月是資料量與時效的折衷：
 *  3 個月只剩 12 園，一頁排不滿；12 個月有 24 園，還不至於把 2019 年的
 *  舊案端上來當「近期輿情」。 */
const MONTHS = 12;

function MediaRow({ park }: { park: MediaPark }) {
  return (
    <article className={s.riskRow}>
      <div>
        <div className={s.rowTitle}>
          <h2>
            {/* 直接帶到詳情頁的新聞輿情分頁並捲到證據鏈，不讓使用者
                進去以後還要自己找哪一個 tab。 */}
            <Link to={`/park/${park.park_id}?tab=${MEDIA_TAB}`}>
              {park.name}
            </Link>
          </h2>
          <TierBadge tier={park.tier} />
        </div>
        <p className={s.rowMeta}>
          {park.town} · 近 {MONTHS} 個月{" "}
          <b className={s.num}>{park.article_count}</b> 則報導 · 最近{" "}
          {park.latest_date}
          {park.top_event_type ? ` · 主要事件 ${park.top_event_type}` : ""}
        </p>
      </div>
    </article>
  );
}

export default function Media() {
  const query = useApi(`/media?months=${MONTHS}`, mediaPageSchema);
  return (
    <>
      <PageHeader
        title={`新聞輿情 — 近 ${MONTHS} 個月`}
        description="依報導則數由多到少。同一起事件被十幾家媒體轉載，報導數本身就是外界關注度的量測；分數不參與這頁的排序。"
      >
        <CopyLink />
      </PageHeader>
      <QueryState query={query}>
        {(data) =>
          data.items.length ? (
            <>
              <p className={s.note}>
                觀察窗 {data.since} ～ {data.as_of}
                （錨在資料集最後一則報導，不是今天，所以同一份資料每次看到的
                名單都一樣）。只列出報導明文點名的園所；沒被點名不代表沒有風險。
              </p>
              <section aria-label="輿情關注度排序">
                {data.items.map((park) => (
                  <MediaRow key={park.park_id} park={park} />
                ))}
              </section>
            </>
          ) : (
            <EmptyState />
          )
        }
      </QueryState>
    </>
  );
}
