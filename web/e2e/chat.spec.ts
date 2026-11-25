import { test, expect } from "@playwright/test";

test("native A2A tables, saved follow-up, agent isolation and mobile layout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Coordinator", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Show two rankings");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("table")).toHaveCount(2);
  await expect(
    page.getByText("Reviewed answer. Previous turns: 0."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Stop generation" }),
  ).not.toBeVisible();
  await page.screenshot({
    path: "test-results/answer-tables.png",
    fullPage: true,
  });
  await page.reload();
  await expect(page.getByRole("table")).toHaveCount(2);
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Compare both rankings");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Reviewed answer. Previous turns: 1."),
  ).toBeVisible();
  await page.getByRole("button", { name: /Inventory agent/ }).click();
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Message" }).fill("Count stock");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByRole("heading", { name: "Inventory analysis" }),
  ).toBeVisible();
  await expect(
    page.getByText("Reviewed answer. Previous turns: 0."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Agent details" }).click();
  await expect(page.getByRole("region", { name: "Agent card" })).toContainText(
    "A2A 1.0",
  );
  await page.getByRole("button", { name: "Close agent details" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".sidebar")).not.toBeInViewport();
  await page.screenshot({
    path: "test-results/answer-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(
    page.getByRole("navigation", { name: "Choose an agent" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("Stop cancels the server task, failure is safe, incomplete outcome is explicit", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Wait for cancellation");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("status")).toContainText("Thinking");
  await expect(page.getByRole("status")).toContainText("1s", { timeout: 5000 });
  await page.getByRole("button", { name: "Stop generation" }).click();
  await expect
    .poll(
      async () =>
        (await (await request.get("/preview-status")).json()).cancelled,
    )
    .toContain("coordinator");
  await expect(
    page.getByText("Stopped. No unfinished answer was published."),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("Fail safely");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Task could not complete (RuntimeError)."),
  ).toBeVisible();
  await expect(
    page.getByText("Never expose this internal detail"),
  ).not.toBeVisible();
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Incomplete answer");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("The available evidence is insufficient."),
  ).toBeVisible();
});
