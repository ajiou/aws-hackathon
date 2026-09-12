import { lazy, Suspense, useEffect } from "react";
import { NavLink, Link, Route, Routes, useLocation } from "react-router-dom";
import {
  ShieldCheck,
  LayoutDashboard,
  ChartNoAxesCombined,
  ClipboardList,
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
const Validation = lazy(() => import("./pages/Validation"));
const Worklist = lazy(() => import("./pages/Worklist"));
// 地圖就是首頁，所以導覽列不再放它；點左上角標誌即可回到地圖。
const navigation = [
  { path: "/overview", label: "總覽搜尋", icon: LayoutDashboard },
  { path: "/validation", label: "成效驗證", icon: ChartNoAxesCombined },
  { path: "/worklist", label: "稽查派工單", icon: ClipboardList },
];
export default function App() {
  const meta = useMeta();
  const location = useLocation();
  useEffect(() => {
    const named: Record<string, string> = {
      "/": "園所風險地圖",
      "/map": "園所風險地圖",
      "/districts": "行政區熱力",
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
            className="flex min-w-0 gap-1 overflow-x-auto py-1"
          >
            {navigation.map(({ path, label, icon: Icon }) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground no-underline transition-colors hover:bg-muted hover:text-foreground",
                    isActive && "bg-accent text-primary",
                  )
                }
              >
                <Icon className="size-4" aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
          {meta.data && (
            <span className="hidden shrink-0 text-xs text-muted-foreground xl:block">
              {number(meta.data.population)} 園 · 資料至{" "}
              {meta.data.data_freshness.punishments}
              {isMock && " · 示範資料"}
            </span>
          )}
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
              <Route path="/validation" element={<Validation />} />
              <Route path="/worklist" element={<Worklist />} />
              <Route
                path="*"
                element={
                  <>
                    <h1>找不到此頁面</h1>
                    <Link to="/">返回總覽搜尋</Link>
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
