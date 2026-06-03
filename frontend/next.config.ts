import type { NextConfig } from "next";

// "" in local dev, "/REPO" on GitHub Pages (set via NEXT_PUBLIC_BASE_PATH in CI).
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig: NextConfig = {
  output: "export", // static HTML export -> GitHub Pages, no Node server
  basePath,
  assetPrefix: basePath || undefined,
  images: { unoptimized: true }, // default next/image loader is unsupported in export
  trailingSlash: true, // directory-style routing on GH Pages without server rewrites
  devIndicators: false,
};

export default nextConfig;
