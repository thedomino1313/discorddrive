# DiscordDrive

## Description:
We aim to create a Python library that can manage a Google Drive file system through a set of Discord bot commands. These commands will be loaded as a “Cog”, which is a collection of commands that can be added to an existing Discord bot. The bot will be able to manage a file system, including creating new directories and adding and retrieving files. This adds a level of privacy to a Google Drive folder, eliminating security risks of users with access deleting files. Admins will import our library, add the Cog to their personal Discord bot, and use their personal Google account and OAuth token to interface with the Google Drive API.

## Stack:
Python

## Goals:
Interface with the Google Drive API using any user’s OAuth token
Generate an initial file structure or link to an existing one
Want to be able to upload files/folders to Google Drive
Want to be able to retrieve files/folders from Google Drive
Support some “root” directory

## Usage:
1. Clone the repository (this will change soon to installing through pip)
2. Get the id of your server, create a file named `.env` in the directory that your bot runs out of, and put the following code in it:
```
set
DD_GUILD_ID=<server id>
```
3. Follow the official [Google quick-start instructions](https://developers.google.com/drive/api/quickstart/python) to generate your credentials file.
4. Save the credentials file as `credentials.json` in the same directory as the .env file.
5. Open Google Drive, go to the directory that you want to root the bot to, and get the link.
   1. It should be of format: `https://drive.google.com/drive/folders/folder_id`
6. Create a Discord bot using Pycord, and add the DiscordDrive command suite to it with the following code:
```python
from discord_drive import DriveAPICommands
bot.add_cog(DriveAPICommands(bot, "<link from step 5>"))
```
7. Run the bot, and use `/authenticate` to ensure that DiscordDrive is authorized to access your Google Account.

## Team:
Ryan Karch (karchr) - Official Project Lead

Dominic Beyer (beyerd) - Co-Project Lead