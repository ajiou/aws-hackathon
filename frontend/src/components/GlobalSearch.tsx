import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { Input } from "./ui/input";
import { Button } from "./ui/button";

export function GlobalSearch() {
  const location = useLocation();
  const navigate = useNavigate();
  const urlSearch = new URLSearchParams(location.search).get("q") ?? "";
  const [search, setSearch] = useState(urlSearch);
  // 這幾頁的搜尋是就地篩選，其餘頁面則導到總覽搜尋。
  const inline = ["/", "/map", "/overview"].includes(location.pathname);
  useEffect(() => {
    setSearch(urlSearch);
  }, [urlSearch, location.pathname]);
  function submit(value: string, replace = false) {
    const params = new URLSearchParams(inline ? location.search : "");
    if (value.trim()) params.set("q", value.trim());
    else params.delete("q");
    params.delete("page");
    params.delete("selected");
    navigate(
      {
        pathname: inline ? location.pathname : "/overview",
        search: params.toString(),
      },
      { replace },
    );
  }
  useEffect(() => {
    if (!inline || search.trim() === urlSearch) return;
    const timer = setTimeout(() => submit(search, true), 300);
    return () => clearTimeout(timer);
  }, [search, urlSearch, location.pathname, location.search]);
  return (
    <form
      role="search"
      aria-label="園所搜尋"
      // basis-96 是想要的寬度，不是保證寬度：導覽列多一個分頁之後，
      // 1280px 下六個元素排不進一行，總得有人讓位。讓搜尋框讓——它縮到
      // 12rem 還打得了字，導覽列少一個像素就有分頁被裁掉看不見。
      className="relative ml-auto w-full min-w-48 shrink basis-96"
      onSubmit={(event) => {
        event.preventDefault();
        submit(search);
      }}
    >
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground"
      />
      <Input
        type="search"
        aria-label="搜尋園名"
        placeholder={
          location.pathname === "/map" || location.pathname === "/"
            ? "搜尋地圖上的幼兒園…"
            : "搜尋幼兒園名稱…"
        }
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="bg-muted pl-10 pr-20 [&::-webkit-search-cancel-button]:hidden"
      />
      <div className="absolute right-1 top-1 flex items-center">
        {search && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="清除搜尋"
            onClick={() => {
              setSearch("");
              submit("");
            }}
          >
            <X />
          </Button>
        )}
        <Button
          type="submit"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="搜尋"
        >
          <Search />
        </Button>
      </div>
    </form>
  );
}
