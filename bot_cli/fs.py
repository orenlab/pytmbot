"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import glob
import os
import shutil
import typing as t
from pathlib import Path
from string import Template


def create_folder_if_not(folder_path: str) -> None:
    """
    Create a folder if it doesn't already exist.

    Args:
        folder_path (str): The path of the folder to create.

    Returns:
        None
    """
    # Create the folder if it doesn't exist
    os.makedirs(os.path.dirname(folder_path), exist_ok=True)


def list_files(directory: str, **kwargs) -> t.List[str]:
    """
    List all files in a directory that match the specified file extension and are not in the ignore list.

    Args:
        directory (str): The directory to search for files.
        **kwargs: Additional keyword arguments.
            ignore (list, optional): A list of files to ignore. Defaults to [""].
            file_extension (str or None, optional): The file extension to filter by. Defaults to None.

    Returns:
        list: A list of file names.
    """
    # Get the ignore list from kwargs, defaulting to [""]
    ignore: list = kwargs.get("ignore", [""])
    # Get the file extension from kwargs, defaulting to None
    file_extension: t.Union[str, None] = kwargs.get("file_extension")

    files: list = []

    # Loop through each file in the directory
    for file in os.listdir(directory):
        # Check if the file is a regular file
        if os.path.isfile(os.path.join(directory, file)):
            # Check if the file should be included based on the ignore list and file extension
            if file not in ignore and (file_extension and file.endswith(file_extension) or not file_extension):
                files.append(file)
    return files


def list_directories(directory: str, ignore: t.Union[None, list] = None) -> t.List[str]:
    """
    List all directories in a given directory, excluding those specified in the ignore list.

    Args:
        directory (str): The directory to search for directories.
        ignore (list, optional): A list of directories to ignore. Defaults to ["__pycache__"].

    Returns:
        list: A list of directory names.
    """
    # Set default ignore list if not provided
    if not ignore:
        ignore = ["__pycache__"]

    # Filter directories based on ignore list and directory check
    return list(
        filter(
            lambda x: os.path.isdir(os.path.join(directory, x)) and x not in ignore,
            os.listdir(directory)
        )
    )


def set_file(file_path: str, file_content: str) -> None:
    """
    Write the given content to the file at the specified file path.

    Args:
        file_path (str): The path to the file.
        file_content (str): The content to write to the file.

    Returns:
        None
    """
    # Open the file in write mode
    with open(file_path, 'w') as f:
        # Write the content to the file
        f.write(file_content)
        # Close the file (not necessary in this case, as the 'with' statement automatically closes the file)
        f.close()


def has_file(file_path: str) -> bool:
    """
    Check if a file exists at the given file path.

    Args:
        file_path (str): The path to the file.

    Returns:
        bool: True if the file exists, False otherwise.
    """
    # Create a Path object from the file path
    potential_file = Path(file_path)

    # Check if the path is a file
    return potential_file.is_file()


def copy_file(src: str, dest: str) -> str:
    """
    Copy a file from the source path to the destination path.

    Args:
        src (str): The source file path.
        dest (str): The destination file path.

    Returns:
        str: The destination file path.

    Raises:
        shutil.Error: If an error occurs during the file copy operation.
    """
    try:
        shutil.copy(src, dest)
        return dest
    except shutil.Error as e:
        raise shutil.Error(f"Error copying file: {e}")


def read_file(file_path: str) -> t.IO:
    """
    Open a file at the specified file path and return a file object.

    Args:
        file_path (str): The path to the file.

    Returns:
        IO: A file object for reading the contents of the file.
    """
    # Open the file in read mode
    file_obj = open(file_path, 'r')

    # Return the file object
    return file_obj


def replace_templates_in_files(
        lookup_path: str,
        file_extension: str,
        template_vars: dict,
        ignore: t.Union[None, t.List[str]] = None
) -> None:
    """
    Replaces templates in files with the given template variables.

    Args:
        lookup_path (str): The path to look for files.
        file_extension (str): The file extension to match.
        template_vars (dict): The template variables to replace.
        ignore (List[str], optional): List of file names to ignore. Defaults to None.

    Returns:
        None
    """
    # Set ignore to an empty list if it's None
    if not ignore:
        ignore: list = []

    # Find all files with the given file extension in the lookup path and its subdirectories
    files: t.List[str] = [f for f in glob.glob(lookup_path + "/**/*%s" % file_extension, recursive=True)]

    # Iterate over each file
    for f in files:
        # Skip files in the ignore list
        if f.split("/")[-1] not in ignore:
            # Open the file for reading
            with open(f, 'r') as file:
                # Read the file content as a template
                template = Template(file.read())

            # Substitute the template variables
            file_content = template.substitute(template_vars)

            # Open the file for writing
            with open(f, 'w') as file:
                # Write the modified content back to the file
                file.write(file_content)
