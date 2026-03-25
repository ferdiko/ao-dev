import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TagDropdown } from "./TagDropdown";
import { TAG_COLORS, type Tag } from "../tags";

const TAGS: Tag[] = [
  { tag_id: "tag-1", name: "Alpha", color: TAG_COLORS[0] },
  { tag_id: "tag-2", name: "Beta", color: TAG_COLORS[1] },
];

afterEach(() => {
  cleanup();
});

describe("TagDropdown", () => {
  it("toggles an existing tag from the dropdown list", () => {
    const onToggle = vi.fn();

    render(
      <TagDropdown
        selectedTags={[]}
        allTags={TAGS}
        onToggle={onToggle}
        onCreate={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Add tags..."));
    fireEvent.click(screen.getByText("Alpha"));

    expect(onToggle).toHaveBeenCalledWith(TAGS[0]);
  });

  it("creates a new tag with the default muted color", () => {
    const onCreate = vi.fn();

    render(
      <TagDropdown
        selectedTags={[]}
        allTags={TAGS}
        onToggle={vi.fn()}
        onCreate={onCreate}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Add tags..."));
    fireEvent.change(screen.getByPlaceholderText("Filter or create tag..."), {
      target: { value: "Gamma" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create/i }));
    fireEvent.click(screen.getByRole("button", { name: "Create tag" }));

    expect(onCreate).toHaveBeenCalledWith("Gamma", TAG_COLORS[0]);
  });

  it("invokes project-wide delete for an existing tag", () => {
    const onDelete = vi.fn();

    render(
      <TagDropdown
        selectedTags={[]}
        allTags={TAGS}
        onToggle={vi.fn()}
        onCreate={vi.fn()}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByText("Add tags..."));
    fireEvent.click(screen.getByTitle('Delete "Alpha"'));

    expect(onDelete).toHaveBeenCalledWith(TAGS[0]);
  });
});
