import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { readFileSync, readdirSync } from "node:fs";
// Ship fixtures only for an explicitly selected mock build. No raw data is served.
export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "watchdog-mock",
      configureServer(server) {
        server.middlewares.use("/mock", (req, res, next) => {
          const file = req.url?.split("?")[0].slice(1);
          if (!file || !/^[a-z-]+\.json$/.test(file)) return next();
          try {
            res.setHeader("Content-Type", "application/json");
            res.end(readFileSync(new URL(`./mock/${file}`, import.meta.url)));
          } catch {
            res.statusCode = 404;
            res.end("{}");
          }
        });
      },
      generateBundle() {
        if (process.env.VITE_API_BASE === "mock" || mode === "mock") {
          for (const file of readdirSync(
            new URL("./mock/", import.meta.url),
          ).filter((f) => f.endsWith(".json"))) {
            this.emitFile({
              type: "asset",
              fileName: `mock/${file}`,
              source: readFileSync(new URL(`./mock/${file}`, import.meta.url)),
            });
          }
        }
      },
    },
  ],
  worker: { format: "es" },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { target: "es2022" },
}));
