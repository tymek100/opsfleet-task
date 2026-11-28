import { test, expect } from "@playwright/test";

test("an interrupted stream is explicit and never resubmits the investigation", async ({ page }) => {
  let sends = 0;
  await page.goto("/");
  await page.route("**/api/agents/coordinator/chat", async route => {
    sends++;
    await route.fulfill({ contentType: "application/x-ndjson", body: '{"type":"started"}\n' });
  });
  await page.getByRole("textbox", { name: "Message" }).fill("Compare sales and stock");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("The connection ended before a reviewed result arrived. The request was not resent.")).toBeVisible();
  expect(sends).toBe(1);
});

test("LangGraph tables, saved follow-up, agent isolation and mobile layout", async ({
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
    "LangGraph",
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
  await expect(
    page.getByRole("button", {
      name: "Delete conversation: Wait for cancellation",
      exact: true,
    }),
  ).toBeDisabled();
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
    page.getByText("The investigation could not complete. No unreviewed answer was published."),
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

test("delete conversations with confirmation, retry, active fallback and persistent history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  async function seed(role: string, title: string) {
    const created = await page.request.post("/api/conversations", {
      data: { role },
    });
    const { id } = await created.json();
    await page.request.post(`/api/conversations/${id}`, {
      data: {
        parentId: null,
        message: {
          id: `${id}-user`,
          role: "user",
          content: [{ type: "text", text: title }],
          createdAt: new Date().toISOString(),
        },
      },
    });
    return id;
  }
  const oldest = await seed("coordinator", "Old conversation");
  await seed("coordinator", "Middle conversation");
  await seed("coordinator", "Latest conversation");
  const inventory = await seed("inventory", "Inventory conversation");
  await page.goto("/");
  const history = page.getByRole("navigation", {
    name: "Conversation history",
  });
  const dialog = page.getByRole("dialog", { name: "Delete conversation?" });
  const oldestDelete = history.getByRole("button", {
    name: "Delete conversation: Old conversation",
    exact: true,
  });
  await expect(
    history.getByRole("button", { name: "Latest conversation", exact: true }),
  ).toHaveAttribute("aria-current", "true");

  // Cancel and Escape preserve both saved history and the active selection.
  await oldestDelete.click();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await oldestDelete.focus();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(oldestDelete).toBeFocused();
  expect((await page.request.get(`/api/conversations/${oldest}`)).ok()).toBe(
    true,
  );

  // A failed deletion stays visible and can be retried without losing the chat.
  await page.route(
    `**/api/conversations/${oldest}`,
    (route) =>
      route.fulfill({ status: 503, json: { error: "Please try again." } }),
    { times: 1 },
  );
  await oldestDelete.click();
  await dialog
    .getByRole("button", { name: "Delete conversation", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Could not delete this conversation",
  );
  await expect(oldestDelete).toBeVisible();
  await dialog
    .getByRole("button", { name: "Delete conversation", exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  await expect(oldestDelete).toHaveCount(0);
  await expect(
    history.getByRole("button", { name: "Latest conversation", exact: true }),
  ).toHaveAttribute("aria-current", "true");
  expect(
    (await page.request.get(`/api/conversations/${oldest}`)).status(),
  ).toBe(404);

  // Deleting the active chat selects another chat belonging to this agent.
  await history
    .getByRole("button", {
      name: "Delete conversation: Latest conversation",
      exact: true,
    })
    .click();
  await dialog
    .getByRole("button", { name: "Delete conversation", exact: true })
    .click();
  await expect(
    history.getByRole("button", { name: "Middle conversation", exact: true }),
  ).toHaveAttribute("aria-current", "true");
  await page.reload();
  await expect(history.getByRole("button")).toHaveCount(2);

  // The last chat can be removed on mobile; its replacement has fresh context.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await history
    .getByRole("button", {
      name: "Delete conversation: Middle conversation",
      exact: true,
    })
    .click();
  await expect(dialog).toBeInViewport();
  await page.screenshot({
    path: "test-results/delete-conversation-mobile.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "Delete conversation", exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  await expect(history.getByRole("button")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Message" }).fill("Start fresh");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Reviewed answer. Previous turns: 0."),
  ).toBeVisible();
  expect((await page.request.get(`/api/conversations/${inventory}`)).ok()).toBe(
    true,
  );
  expect(errors).toEqual([]);
});
