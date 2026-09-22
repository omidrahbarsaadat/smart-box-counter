# GitHub and Vercel deployment

The `web/` application is a zero-build static site. Visitors need only a current browser and the deployed HTTPS URL—no Python, OpenCV, Node.js, or local installation.

## 1. Publish to GitHub

Create a public GitHub repository and push this project. From the project folder:

```bash
git init -b main
git add .
git commit -m "Build Smart Box Counter browser and desktop editions"
git remote add origin https://github.com/YOUR-USER/smart-box-counter.git
git push -u origin main
```

The repository contains both editions. Vercel serves only `web/`; the Python/OpenCV source remains available to reviewers and desktop users.

## 2. Deploy to Vercel from GitHub

1. Sign in to [Vercel](https://vercel.com/) and choose **Add New → Project**.
2. Import the `smart-box-counter` GitHub repository.
3. Leave the repository root as the Root Directory.
4. Vercel reads `vercel.json`: Framework is **Other**, no build command is needed, and Output Directory is `web`.
5. Choose **Deploy**.
6. Open the generated HTTPS URL, click **Start camera**, and approve browser camera access.

Every push to the tracked GitHub branch triggers a new Vercel deployment automatically.

## What works on Vercel

- Webcam access through the browser's secure `getUserMedia` API
- Local video analysis with deterministic frame sampling
- Background-based rectangular box detection
- Persistent centroid tracking and tracking-loss tolerance
- One count per tracking ID when its center crosses the configured line
- Red, blue, green, yellow, white, black, brown, and unknown HSV classification
- Calibration controls, pixel HSV inspection, overlay, totals, and FPS/progress
- IndexedDB event/snapshot persistence and CSV export

Camera frames remain in the browser. The static deployment has no upload endpoint.

## Important production distinction

The browser edition stores data per browser/device in IndexedDB. It is immediately usable with no backend or account. For a factory-wide shared database, multi-user dashboard, or centrally managed records, add an authenticated database API. The desktop Python edition already supports local SQLite and optional YOLO26 + ByteTrack.

## Camera checklist

- Use Vercel's HTTPS URL; camera access is blocked on ordinary non-HTTPS remote pages.
- Keep the camera fixed and use even lighting.
- Leave the detection area empty for the short background-learning phase.
- Move one matte box steadily across the amber line for the first test.
- If another application owns the camera, close it and retry.
