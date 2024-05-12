Start with:
```sh
docker run -d --name timezonebot  \
--env-file .env \
--cpus="0.50" \
--memory=100m \
--restart on-failure \
-v data:/timezonebot/data \
timezonebot:latest
```
