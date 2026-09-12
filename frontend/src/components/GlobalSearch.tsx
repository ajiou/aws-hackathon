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
  const inline = location.pathname === "/" || location.pathname === "/map";
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
      { pathname: inline ? location.pathname : "/", search: params.toString() },
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
      className="relative ml-auto w-full max-w-sm"
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
          location.pathname === "/map"
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
