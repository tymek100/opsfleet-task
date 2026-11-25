import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, toCsv } from "./Markdown";
import { conversationForAgent } from "./api";

describe("reviewed answer presentation", () => {
  it("renders two real tables without changing values or executing HTML", () => {
    render(
      <Markdown
        text={
          "| Product | Revenue |\n|---|---:|\n| Coat | 259.99 |\n\n| Product | Customers |\n|---|---:|\n| Dress | 3 |\n\n<script>alert(1)</script>"
        }
      />,
    );
    expect(screen.getAllByRole("table")).toHaveLength(2);
    expect(screen.getByText("259.99")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "Download table as CSV" }),
    ).toHaveLength(2);
  });
  it("preserves exported values and quotes delimiters, preventing formula execution", () => {
    expect(
      toCsv([
        ["Product", "Revenue"],
        ['Coat, "red"', "-123.45"],
        ["=1+1", "259.99"],
      ]),
    ).toBe(
      '"Product","Revenue"\r\n"Coat, ""red""","-123.45"\r\n"\'=1+1","259.99"',
    );
  });
  it("never resumes another agent conversation", () => {
    const history = [
      { id: "a", role: "retail", title: "Sales" },
      { id: "b", role: "inventory", title: "Stock" },
    ];
    expect(conversationForAgent(history, "inventory")?.id).toBe("b");
    expect(conversationForAgent(history, "coordinator")).toBeUndefined();
  });
});
