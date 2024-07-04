Start with:
```sh
docker run -d --name timezone-bot  \
--env-file .env \
--cpus="0.50" \
--memory=100m \
--restart on-failure \
-v data:/timezonebot/data \
timezone-bot:latest
```
