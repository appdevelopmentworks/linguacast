/** @type {import('next').NextConfig} */
const nextConfig = {
  // Tauri serves a static frontend, so Next.js must produce a static export.
  output: "export",
  // The Tauri webview has no Next.js image optimization server.
  images: { unoptimized: true },
};

export default nextConfig;
