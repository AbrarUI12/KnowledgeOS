import path from "node:path";
import type { NextConfig } from "next";

// Static showcase build for GitHub Pages (.github/workflows/pages.yml): no server, placeholder
// data only. KOS_BASE_PATH is the repo sub-path Pages serves from (e.g. /KnowledgeOS).
const staticExport = process.env.KOS_STATIC_EXPORT === "1";

const nextConfig: NextConfig = {
  // Self-contained server bundle for infra/docker/web.Dockerfile (Vercel ignores this).
  output: staticExport ? "export" : "standalone",
  ...(staticExport && {
    basePath: process.env.KOS_BASE_PATH || undefined,
    trailingSlash: true,
    images: { unoptimized: true },
  }),
  // Monorepo: trace dependencies from the repository root (pnpm workspace).
  outputFileTracingRoot: path.join(__dirname, "../.."),
  // Partial prerendering needs a server; the static export turns both off.
  cacheComponents: !staticExport,
  partialPrefetching: !staticExport,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
