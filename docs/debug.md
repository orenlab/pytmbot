# Run pyTMbot v.2 in DEBUG mode

- To begin with, if the container containing the bot is running, it should be stopped:

```bash
sudo docker stop pytmbot
```

- Deleting the stopped container:

```bash
sudo docker rm pytmbot
```

- Run pyTMbot in DEBUG mode:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/.pytmbotenv:/opt/app/.pytmbotenv:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:latest \
--log-level=DEBUG --mode=prod
```

- You can access the bot's logs using the following command:

```bash
sudo docker logs pytmbot
```
