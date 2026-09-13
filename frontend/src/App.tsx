import { lazy, Suspense, useEffect } from "react";
import { NavLink, Link, Route, Routes, useLocation } from "react-router-dom";
import {
  ShieldCheck,
  LayoutDashboard,
  Map,
  ClipboardList,
  Newspaper,
} from "lucide-react";
import { useMeta } from "./api/queries";
import { isMock } from "./api/client";
import { Skeleton } from "./components/common";
import { GlobalSearch } from "./components/GlobalSearch";
import { cn } from "./lib/utils";
import { number } from "./utils/format";
import s from "./styles/App.module.css";
const Overview = lazy(() => import("./pages/Overview"));
const Risk = lazy(() => import("./pages/Risk"));
const ParkDetail = lazy(() => import("./pages/ParkDetail"));
const Districts = lazy(() => import("./pages/Districts"));
const MapPage = lazy(() => import("./pages/MapPage"));
const Worklist = lazy(() => import("./pages/Worklist"));
const Media = lazy(() => import("./pages/Media"));
// 地圖是首頁，但它仍然要在導覽列出現：只靠左上角標誌回首頁的話，畫面上就沒有
// 任何地方顯示「你現在在地圖」。兩個分頁並列、目前所在的那個畫底線。
const navigation = [
  // alias：/map 跟 / 是同一頁，兩個網址都要讓地圖分頁亮著，否則從舊連結進來
  // 會看到兩個分頁都沒有底線。
  { path: "/", alias: "/map", label: "園所風險地圖", icon: Map },
  { path: "/overview", label: "總覽搜尋", icon: LayoutDashboard },
  { path: "/media", label: "新聞輿情", icon: Newspaper },
];
export default function App() {
  const meta = useMeta();
  const location = useLocation();
  useEffect(() => {
    const named: Record<string, string> = {
      "/map": "園所風險地圖",
      "/districts": "行政區熱力",
      "/worklist": "稽查派工單",
      "/media": "新聞輿情",
    };
    document.title = `${navigation.find(({ path }) => path === location.pathname)?.label ?? named[location.pathname] ?? "單園分析"} · 小小守護員`;
  }, [location.pathname]);
  return (
    <>
      <a href="#main" className={s.skip}>
        跳至主要內容
      </a>
      <header
        className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-md"
        data-topbar
      >
        <div className="flex flex-wrap items-center gap-4 px-4 py-4 md:flex-nowrap md:px-6">
          <Link
            className="flex shrink-0 items-center gap-3 text-foreground no-underline"
            to="/"
          >
            <span className="flex size-10 items-center justify-center rounded-xl bg-primary text-white">
              <ShieldCheck aria-hidden="true" className="size-6" />
            </span>
            <span className="text-base font-semibold">
              小小守護員{" "}
              <small className="block text-xs font-normal tracking-wider text-muted-foreground">
                SMART WATCHDOG
              </small>
            </span>
          </Link>
          <span className="hidden border-l border-border pl-4 text-xs text-muted-foreground lg:block">
            新北市教保機構
            <br />
            稽查決策輔助系統
          </span>
          <GlobalSearch />
          {/* 導覽列接在搜尋框右邊，不再自成一排。 */}
          <nav
            aria-label="主要導覽"
            // lg 以上導覽列定寬、由搜尋框讓位，分頁一個都不裁。lg 以下
            // md:flex-nowrap 把整列鎖成一行，導覽列再定寬就會把 header
            // 撐出橫向捲軸，所以窄螢幕還是讓導覽列自己橫向捲。
            className="flex min-w-0 gap-1 overflow-x-auto py-1 lg:min-w-fit lg:shrink-0"
          >
            {navigation.map(({ path, alias, label, icon: Icon }) => {
              const isActive =
                location.pathname === path || location.pathname === alias;
              return (
                <Link
                  key={path}
                  to={path}
                  aria-current={isActive ? "page" : undefined}
                  // 目前分頁用底線標示。底色色塊在深色主題下跟 hover 狀態幾乎
                  // 分不出來，實測會讓人不確定自己在哪一頁。
                  className={cn(
                    "flex shrink-0 items-center gap-2 border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground no-underline transition-colors hover:text-foreground",
                    isActive && "border-primary text-primary",
                  )}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  <span>{label}</span>
                </Link>
              );
            })}
          </nav>
          {meta.data && (
            <span className="hidden shrink-0 text-xs text-muted-foreground xl:block">
              {number(meta.data.population)} 園 · 資料至{" "}
              {meta.data.data_freshness.punishments}
              {isMock && " · 示範資料"}
            </span>
          )}
          {/* 派工單是「產出」而不是瀏覽用的分頁，所以放在右上角當動作按鈕。 */}
          <NavLink
            to="/worklist"
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium no-underline transition-colors hover:bg-muted",
                isActive ? "bg-accent text-primary" : "text-foreground",
              )
            }
          >
            <ClipboardList className="size-4" aria-hidden="true" />
            稽查派工單
          </NavLink>
        </div>
      </header>
      <div data-layout>
        <main id="main" className={s.content} tabIndex={-1}>
          <Suspense fallback={<Skeleton />}>
            <Routes>
              <Route path="/" element={<MapPage />} />
              <Route path="/overview" element={<Overview />} />
              <Route path="/risk" element={<Risk />} />
              <Route path="/map" element={<MapPage />} />
              <Route path="/park/:id" element={<ParkDetail />} />
              <Route path="/districts" element={<Districts />} />
              <Route path="/worklist" element={<Worklist />} />
              <Route path="/media" element={<Media />} />
              <Route
                path="*"
                element={
                  <>
                    <h1>找不到此頁面</h1>
                    <Link to="/">返回園所風險地圖</Link>
                  </>
                }
              />
            </Routes>
          </Suspense>
        </main>
      </div>
    </>
  );
}
