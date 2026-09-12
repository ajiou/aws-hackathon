import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Link, Route, Routes, useLocation } from "react-router-dom";
import { useMeta } from "./api/queries";
import { isMock } from "./api/client";
import { Skeleton, QueryState } from "./components/common";
import { number } from "./utils/format";
import s from "./styles/App.module.css";
const Overview = lazy(() => import("./pages/Overview"));
const Risk = lazy(() => import("./pages/Risk"));
const ParkDetail = lazy(() => import("./pages/ParkDetail"));
const Districts = lazy(() => import("./pages/Districts"));
const MapPage = lazy(() => import("./pages/MapPage"));
const Validation = lazy(() => import("./pages/Validation"));
const Worklist = lazy(() => import("./pages/Worklist"));
const navigation = [
  ["/", "總覽搜尋", "⌕"],
  ["/risk", "風險列表", "≡"],
  ["/map", "地圖", "⌖"],
  ["/districts", "行政區熱力", "▦"],
  ["/validation", "成效驗證", "↗"],
  ["/worklist", "稽查派工單", "▤"],
];
export default function App() {
  const meta = useMeta();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const nav = useRef<HTMLElement>(null);
  const menu = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setOpen(false);
    document.title = `${navigation.find(([path]) => path === location.pathname)?.[1] ?? "單園分析"} · 小小守護員`;
  }, [location.pathname]);
  useEffect(() => {
    if (open) nav.current?.querySelector("a")?.focus();
  }, [open]);
  return (
    <>
      <a href="#main" className={s.skip}>
        跳至主要內容
      </a>
      <header className={s.topbar} data-topbar>
        <Link className={s.brand} to="/">
          <span className={s.brandIcon} aria-hidden="true">
            ◇
          </span>
          <span>
            小小守護員 <small>Smart Watchdog</small>
          </span>
        </Link>
        <button
          ref={menu}
          className={s.mobileMenu}
          aria-expanded={open}
          aria-controls="main-navigation"
          onClick={() => setOpen(!open)}
        >
          ☰ 選單
        </button>
        <div className={s.metadata}>
          <QueryState query={meta}>
            {(data) => (
              <>
                母體 {number(data.population)} 園 · 資料至{" "}
                {data.data_freshness.punishments}
                <br />
                切點 {data.cutoff} · v{data.version}
                {isMock && " · 示範資料"}
              </>
            )}
          </QueryState>
        </div>
      </header>
      <div className={s.layout} data-layout>
        {open && (
          <button
            aria-label="關閉導覽選單"
            className={s.drawerBackdrop}
            onClick={() => {
              setOpen(false);
              menu.current?.focus();
            }}
          />
        )}
        <nav
          ref={nav}
          id="main-navigation"
          className={`${s.nav} ${open ? s.navOpen : ""}`}
          aria-label="主要導覽"
          onKeyDown={(e) => {
            if (!open) return;
            if (e.key === "Escape") {
              setOpen(false);
              menu.current?.focus();
            }
            if (e.key === "Tab") {
              const links = nav.current?.querySelectorAll("a");
              if (!links?.length) return;
              const first = links[0],
                last = links[links.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
              }
            }
          }}
        >
          {navigation.map(([path, label, icon]) => (
            <NavLink
              key={path}
              to={path}
              end={path === "/"}
              title={label}
              aria-label={label}
            >
              <span className={s.navIcon} aria-hidden="true">
                {icon}
              </span>
              <span className={s.navLabel}>{label}</span>
            </NavLink>
          ))}
          <small>
            新北市教保機構
            <br />
            稽查決策輔助系統
            <br />
            <br />
            分數代表查核優先序，
            <br />
            不等同違規認定。
          </small>
        </nav>
        <main id="main" className={s.content} tabIndex={-1}>
          <Suspense fallback={<Skeleton />}>
            <Routes>
              <Route path="/" element={<Overview />} />
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
