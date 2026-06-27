import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker image can run
  // `node server.js` without the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
