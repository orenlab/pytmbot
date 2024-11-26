# Running pyTMBot v.0.2.0 in DEBUG Mode

To run pyTMBot v.0.2.0 in DEBUG mode, follow these steps:

1. **Stop the Running Container**

   If the pyTMBot container is currently running, you need to stop it first:

   ```bash
   sudo docker stop pytmbot
   ```

2. **Remove the Stopped Container**

   Once the container is stopped, remove it:

   ```bash
   sudo docker rm pytmbot
   ```

3. **Run pyTMBot in DEBUG Mode**

   Launch the pyTMBot container in DEBUG mode by executing the following command:

   ```bash
   sudo docker run -d \
   -v /var/run/docker.sock:/var/run/docker.sock:ro \
   -v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
   --env TZ="Asia/Yekaterinburg" \
   --restart=always \
   --name=pytmbot \
   --pid=host \
   --security-opt=no-new-privileges \
   orenlab/pytmbot:latest \
   --log_level DEBUG --mode prod
   ```

    - `--log_level DEBUG`: Sets the logging level to DEBUG, providing detailed information for troubleshooting.
    - `--mode prod`: Specifies the production mode for the bot.

4. **Access the Bot’s Logs**

   To view the logs for the pyTMBot container, use the following command:

   ```bash
   sudo docker logs pytmbot
   ```

   This will display the log output for the bot, including detailed DEBUG information.
