# SG driving Reels: auto-posting

Same setup as Mug Smarter / list.sg (Claude Doc "Automated Instagram Posting with GitHub Actions").

- **One Reel every 2 days at 19:30 SGT.** Each item's `post.json` has `post_on` and `post_time` from `caption.md` in `../posts/<item>/`.
- cron-job.org calls the workflow **daily at 19:30 SGT**; days with nothing dated just log "Nothing due".
- GitHub's own schedule (19:30–21:30 SGT, hourly) is the backup and only posts items due in the last 3 h.
- **A missed post blocks the ones after it.** Run the workflow with `catch_up` ticked to post them in date order.
- Reels: `reel.mp4` posts as a Reel (shared to feed); `**Cover:** N s` in `caption.md` picks the cover frame.
- **TikTok is manual:** upload the same `reel.mp4` with the same caption.

## Make and queue a new Reel

```sh
cd ../reels
npm run tts <reel-id>          # voice lines -> public/vo/<id>/ + timings
npm run render <reel-id>       # -> out/<id>.mp4 (-15 LUFS)
cp out/<id>.mp4 ../posts/<NN_name>/reel.mp4   # plus caption.md (Post on / Time / Cover / caption)

cd ../ig-queue
python3 queue_add.py ../posts/<NN_name>
python3 publish.py status
git add queue && git commit -m "Queue <NN_name>" && git pull --rebase && git push
```

Only queue Reels whose rules have been checked against the TP handbooks: pushed media is public on GitHub Pages at once.
Hold one back with `"approved": false` in its `post.json`, then push.
