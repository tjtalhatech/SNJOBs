import express from "express";
import path from "path";
import fs from "fs";
import { spawn } from "child_process";

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // API to trigger the Python fetch script
  app.post("/api/fetch-jobs", (req, res) => {
    const { adzuna_countries } = req.body;
    console.log(`Triggering job fetch for countries: ${adzuna_countries || "default"}...`);
    
    const env = {
      ...process.env,
      ADZUNA_APP_ID: process.env.ADZUNA_APP_ID || "f266c3fa",
      ADZUNA_APP_KEY: process.env.ADZUNA_APP_KEY || "76b85cb7bd4ad52e2ef4eaef72021150",
      RAPIDAPI_KEY: process.env.RAPIDAPI_KEY || "41a049b424mshf21054d61123154p1440c0jsnbf5b27a8411f",
      ADZUNA_COUNTRIES: adzuna_countries || process.env.ADZUNA_COUNTRIES || "us,gb,in,ca,au"
    };
    
    const pythonProcess = spawn("python3", [
      path.join(process.cwd(), "fetch_jobs.py")
    ], { env });

    let output = "";
    pythonProcess.stdout.on("data", (data) => output += data.toString());
    pythonProcess.stderr.on("data", (data) => console.error(`Script error: ${data}`));

    pythonProcess.on("close", (code) => {
      if (code === 0) {
        res.json({ success: true, message: "Jobs updated successfully", log: output });
      } else {
        res.status(500).json({ success: false, message: `Script failed with code ${code}` });
      }
    });
  });

  // Serve the jobs data
  app.get("/api/jobs", (req, res) => {
    const dataPath = path.join(process.cwd(), "public", "data", "jobs.json");
    if (fs.existsSync(dataPath)) {
      res.sendFile(dataPath);
    } else {
      res.json({ jobs: [], updated_at: null });
    }
  });

  if (process.env.NODE_ENV !== "production") {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*all", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
