# Launcher artwork

`bg*.jpg` and `logo*.png` are converted from the images of the official OpenGOAL launcher
(https://github.com/open-goal/launcher, commit 8c58833, `src/assets/images/`), which is published under the ISC license
(`LICENSE-open-goal-launcher.txt`). The game artwork itself belongs to Naughty Dog / Sony Interactive Entertainment; it is shown
here the same way the OpenGOAL launcher shows it, to identify the games.

Conversion (Pillow): the backgrounds are resized to 1920x1080 and saved as JPEG quality 80, the logos are saved as optimized RGBA PNG.

| File | Launcher source |
|---|---|
| `bg1.jpg` | `public/images/jak1/sandover.jpg` |
| `bg2.jpg`, `bg3.jpg` | `src/assets/images/background-jak2.webp`, `background-jak3.webp` |
| `logo1.png`, `logo2.png`, `logo3.png` | `src/assets/images/jak-tpl.webp`, `jak-2.webp`, `jak-3.webp` |

`app/gen_launcher_assets.py` embeds these six files into the app.
