import { it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { RiskScore, ReasonList } from "../components/common";
import { metaSchema, parkSchema } from "../api/types";
import { Timeline } from "../pages/ParkDetail";
const read = (name: string) =>
  JSON.parse(readFileSync(`mock/${name}.json`, "utf8"));
it("keeps every post-cutoff entry above the divider after expanding and preserves null fine text", () => {
  const park = parkSchema.parse(read("scores").items[0]);
  park.timeline = Array.from({ length: 12 }, (_, i) => ({
    date: i < 10 ? "2025-03-14" : "2024-03-14",
    category: "超收",
    law: "第8條第6項",
    fine: null,
    penalty_raw: "停止招生",
    is_after_cutoff: i < 10,
  }));
  const { container } = render(<Timeline park={park} cutoff="2025-01-01" />);
  expect(
    container.querySelectorAll("[data-timeline-item]:not([hidden])"),
  ).toHaveLength(8);
  fireEvent.click(screen.getByRole("button", { name: "展開其餘 4 筆" }));
  expect(
    container.querySelectorAll("[data-timeline-item]:not([hidden])"),
  ).toHaveLength(12);
  const divider = screen.getByText("切點 2025-01-01");
  expect(divider.previousElementSibling?.querySelectorAll("li")).toHaveLength(
    10,
  );
  expect(divider.nextElementSibling?.querySelectorAll("li")).toHaveLength(2);
  expect(screen.getAllByText(/停止招生/)).toHaveLength(12);
  expect(screen.queryByText(/罰鍰 0 元/)).not.toBeInTheDocument();
});
it("shows institution-specific weights, missing operation note, and supplied reasons", () => {
  const park = parkSchema.parse(read("scores").items[0]);
  render(
    <MemoryRouter>
      <RiskScore park={park} meta={metaSchema.parse(read("meta"))} />
    </MemoryRouter>,
  );
  expect(
    screen.getByText("私立幼兒園依法不需公告財務報告"),
  ).toBeInTheDocument();
  expect(screen.getByText(park.reasons[0].label)).toBeInTheDocument();
  expect(screen.getByText(/50.0%/)).toBeInTheDocument();
});
it("preserves backend reason ordering and exposes unvalidated note to keyboard users", () => {
  render(
    <ReasonList
      reasons={[
        {
          code: "a",
          label: "後端第一條",
          weight: 0.1,
          dimension: "operation",
          validated: false,
        },
        {
          code: "b",
          label: "後端第二條",
          weight: 0.9,
          dimension: "evaluation",
          validated: true,
        },
      ]}
    />,
  );
  expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("後端第一條");
  expect(
    screen.getByRole("button", { name: /尚無足夠裁罰樣本/ }),
  ).toBeInTheDocument();
});
