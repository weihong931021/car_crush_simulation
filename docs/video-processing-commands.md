# 處理影片的終端機指令

影片下載 → 拆幀 → RIFE 補幀 → 重新合成的常用 CLI 指令速查。

> RIFE 補幀對 YOLO 偵測品質的影響見 [TrafficLab 偵測優化進度](../CLAUDE.md)：4x 補幀偵測品質**下降**，AI 生成幀會干擾 YOLO，僅用於播放流暢度，不用於偵測。

## 1. 下載影片（yt-dlp）

```bash
yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  --cookies-from-browser chrome "影片網址"
```

- `--cookies-from-browser chrome`：用 Chrome 的登入 cookie，可下載需登入/會員影片。

## 2. 拆解影片成影格（ffmpeg）

```bash
ffmpeg -i test5.mp4 input_frames/frame_%08d.png
```

- 輸出到 `input_frames/`，檔名 8 位數補零（`frame_00000001.png`…）。

## 3. 補幀（RIFE，rife-ncnn-vulkan）

### 兩倍補幀

```bash
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -u
rm output_frames/.DS_Store   # 移除 macOS 產生的隱藏檔，避免合成時報錯
```

### 四倍補幀（上面這種比較好）

```bash
# 方式 A：指定輸出總幀數
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -n 940 -u

# 方式 B：兩次兩倍串接（2x → 再 2x = 4x），品質較佳
./rife-ncnn-vulkan -i input_frames -o mid_frames -m models/rife-v4.6 -u && \
  ./rife-ncnn-vulkan -i mid_frames -o output_frames -m models/rife-v4.6 -u
```

- `-m models/rife-v4.6`：使用的模型。
- `-n 940`：指定輸出影格總數。
- `-u`：UHD / 高解析度模式。

## 4. 指定幀率合成影片（ffmpeg）

```bash
# 30fps
ffmpeg -framerate 30 -i output_frames/%08d.png -c:v libx264 -crf 20 \
  -pix_fmt yuv420p test21-3sf.mp4

# 50fps（另一組來源資料夾 point/）
ffmpeg -framerate 50 -i point/%08d.png -c:v libx264 -crf 20 \
  -pix_fmt yuv420p output_framer1.mp4
```

- `-framerate`：輸出影片的播放幀率。
- `-crf 20`：畫質（數字越小越好，18–23 為常用範圍）。
- `-pix_fmt yuv420p`：確保大多數播放器/瀏覽器相容。
