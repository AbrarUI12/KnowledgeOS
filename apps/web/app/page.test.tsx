import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home page", () => {
  it("renders the product name as the main heading", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 1, name: "KnowledgeOS" })).toBeInTheDocument();
  });
});
