import sys

from docker.errors import APIError

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import bot_logger

_updated = []


def _pull_docker_image(image):
    """
    Pull the given docker image, printing data to stdout to
    keep the user informed of progress.
    :param image:
        The name of the image to pull down.
    """
    bot_logger.info("Pulling image {}".format(image))
    attached_to_tty = sys.stdout.isatty()

    with DockerAdapter() as client:

        for _ in client.api.pull(image, stream=True):
            if not attached_to_tty:
                continue
            sys.stdout.write('.')
            sys.stdout.flush()

        if attached_to_tty:
            sys.stdout.write("\n")


def update_image(image):
    """
    Update the given docker image.

    :param image:
        The image to update, in the form of `ubuntu` or `ubuntu:latest`.
    :returns:
        True if the image is updated, False if it is already the latest version.
    """
    with DockerAdapter() as client:
        try:
            bot_logger.debug("Inspecting image {}".format(image))
            image_id = client.api.inspect_image(image)['Id']
            bot_logger.debug("Image id: {}".format(image_id))
        except APIError as e:
            if e.response.status_code == 404:
                bot_logger.warning(
                    "404 response from docker API, assuming image does not "
                    "exist locally"
                )
                image_id = None
            else:
                raise

            _pull_docker_image(image)
            bot_logger.debug("New image id: {}".format(image_id))
            if image_id != client.api.inspect_image(image)['Id']:
                bot_logger.debug("Image IDs differ before and after pull, image was updated")
                _updated.append(image)
                return True

            bot_logger.debug("Image IDs identical before and after pull")
            return False


if __name__ == '__main__':
    update_image('orenlab/pytmbot')
    print(_updated)
