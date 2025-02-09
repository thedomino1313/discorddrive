import cv2
import discord
import math
import numpy as np
import os
import pathlib
import sys

from asyncio import sleep
from time import time
from collections import defaultdict, deque
from datetime import datetime
from discord.ext.commands import has_permissions, MissingPermissions
from discord.ext.pages import Paginator, Page
from mimetypes import guess_extension
from pprint import pprint
from typing import List

from ._drive import DriveAPI
from ._utils import empty_dir

class DriveAPICommands(discord.ext.commands.Cog, command_attrs = dict(guild_only=True)):
    
    _drive_state = defaultdict(lambda: defaultdict(id=None, folders=[], files=[]))
    _wd_cache = None
    

    def __init__(self, bot: discord.ext.commands.Bot, root:str):
        """Initializes the API connection and cache

        Args:
            bot (discord.ext.commands.Bot): Discord bot instance
            root (str): Link to the root folder
        """
        self.bot = bot
        self.API = DriveAPI(root)
        self.root = self.API.ROOT
        self.root_path = pathlib.Path(self.root)
        
        if self.API.service is not None:
            items = self.API.search(parent=self.API.ROOT_ID, page_size=100, recursive=True)
            DriveAPICommands._drive_state[self.root_path]["id"] = self.API.ROOT_ID
            DriveAPICommands._drive_state[self.root_path]["folders"] = [folder["name"] for folder in items if folder['mimeType'].startswith(self.API.FOLDER_TYPE)]
            DriveAPICommands._drive_state[self.root_path]["files"] = [file["name"] for file in items if not file['mimeType'].startswith(self.API.FOLDER_TYPE)]
        
        # self.root_alias = '~'
        self.capacity = 15
        
        DriveAPICommands._wd_cache = defaultdict(lambda: [pathlib.Path(self.root), pathlib.Path(self.root)])
        
    async def _API_ready(self, ctx: discord.ApplicationContext):
        if not (result := bool(self.API.service)):
            await ctx.send_response("Please use `/authenticate` to validate your Google Account's credentials before using any commands!")
        return result
    
    async def _get_user_color(self, ctx: discord.ApplicationContext) -> discord.Colour:
        avatar_byte_array = await ctx.author.display_avatar.with_format("png").read()
        arr = np.asarray(bytearray(avatar_byte_array), dtype=np.uint8)
        img = cv2.imdecode(arr, -1)
        
        red = int(np.average(img[:, :, 0]))
        green = int(np.average(img[:, :, 1]))
        blue = int(np.average(img[:, :, 2]))
        
        color_as_hex = int(f"0x{red:02x}{green:02x}{blue:02x}", base=16)

        return discord.Colour(color_as_hex)

    # @discord.ext.commands.Cog.listener()
    async def cog_command_error(self, ctx: discord.ApplicationContext, error):
        if isinstance(error, MissingPermissions):
            await ctx.send_response("You are missing permission(s) to run this command.")
        else:
            raise error

    # @with_call_order
    @discord.ext.commands.slash_command(name="upload", description="Upload a file to your Google Drive")
    async def upload(self, ctx: discord.ApplicationContext, file: discord.SlashCommandOptionType.attachment):

        if not await self._API_ready(ctx):
            return
        
        await ctx.defer()

        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        result = await self.API.upload_from_discord(file=file, parent=folder_id)
        if result:
            files = self.API.search(parent=folder_id, folders=False, page_size=100, recursive=True)
            DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["files"] = [file["name"] for file in files]

            user_color = await self._get_user_color(ctx)
            embed = discord.Embed(
                title=f"Upload Files",
                color=user_color, # Pycord provides a class with default colors you can choose from
            )

            embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

            embed.add_field(name="", value=result, inline=True)

            embed.set_footer(text=DriveAPICommands._wd_cache[ctx.author.id][0])

            await ctx.send_followup(embed=embed)
        else:
            return
    
    @discord.ext.commands.slash_command(name="pwd", description="Print your current working directory")
    async def pwd(self, ctx: discord.ApplicationContext):

        if not await self._API_ready(ctx):
            return

        user_color = await self._get_user_color(ctx)
        
        embed = discord.Embed(
            title=f"Current Working Directory",
            description=f"{DriveAPICommands._wd_cache[ctx.author.id][0]}",
            color=user_color, # Pycord provides a class with default colors you can choose from
        )

        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        
        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        
        items = self.API.search(parent=folder_id, page_size=100, recursive=True)
        folders = [folder["name"] for folder in items if folder['mimeType'].startswith(self.API.FOLDER_TYPE)]
        files = [file["name"] for file in items if not file['mimeType'].startswith(self.API.FOLDER_TYPE)]
        
        embed.add_field(name="Folders", value=f"{len(folders)}", inline=True)
        embed.add_field(name="Files", value=f"{len(files)}", inline=True)
    
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"] = folder_id
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["folders"] = folders
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["files"] = files
        
        await ctx.send_response(embed=embed, ephemeral=True)
        # await ctx.send_response(f"`{DriveAPICommands._wd_cache[ctx.author.id][0]}`", ephemeral=True)
    
    async def _get_folders(ctx: discord.AutocompleteContext):
        return ["~", "..", *DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.interaction.user.id][0]]["folders"]]

    @discord.ext.commands.slash_command(name="cd", description="Change your current working directory")
    async def cd(self, ctx: discord.ApplicationContext, path: discord.Option(str, "Pick a folder", autocomplete=discord.utils.basic_autocomplete(_get_folders))): # type: ignore
        
        if not await self._API_ready(ctx):
            return
        
        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        
        last_path = DriveAPICommands._wd_cache[ctx.author.id][0]
        DriveAPICommands._wd_cache[ctx.author.id][1] = last_path
        
        user_color = await self._get_user_color(ctx)
        embed = discord.Embed(
            title=f"Change Directory",
            color=user_color, # Pycord provides a class with default colors you can choose from
        )

        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

        if path == "" or path == '~':
            # last_path = DriveAPICommands._wd_cache[ctx.author.id]
            DriveAPICommands._wd_cache[ctx.author.id][0] = pathlib.Path(self.root)
            folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
            # DriveAPICommands._wd_cache[ctx.author.id][1] = last_path
        
        elif path == '.':
            # say something like path not changed
            return
        
        elif path == "..":
            cwd = DriveAPICommands._wd_cache[ctx.author.id][0]
            if cwd != pathlib.Path(self.root):
                DriveAPICommands._wd_cache[ctx.author.id][0] = cwd.parent # get first ancestor
                folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
            else:
                embed.add_field(name="", value="You are in the root directory.", inline=True)
                await ctx.send_response(embed=embed, ephemeral=True)
                return
                
        elif path == '-':
            DriveAPICommands._wd_cache[ctx.author.id][0] = DriveAPICommands._wd_cache[ctx.author.id][1]
            folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]

        else:
            
            user_current_path = DriveAPICommands._wd_cache[ctx.author.id][0]
            folder = self.API.search(file_name=path, parent=DriveAPICommands._drive_state[user_current_path]["id"], files=False)

            # await ctx.send_response(f"{folder}")
            
            if not folder:
                embed.add_field(name="", value=f"{path} is not reachable from your current directory.", inline=True)
                await ctx.send_response(embed=embed, ephemeral=True)
                return

            path, folder_id = folder[0]["name"], folder[0]["id"]
            DriveAPICommands._wd_cache[ctx.author.id][0] /= path
        
        items = self.API.search(parent=folder_id, page_size=100, recursive=True)
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"] = folder_id
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["folders"] = [folder["name"] for folder in items if folder['mimeType'].startswith(self.API.FOLDER_TYPE)]
        DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["files"] = [file["name"] for file in items if not file['mimeType'].startswith(self.API.FOLDER_TYPE)]
        
        embed.add_field(name="", value=f"Directory changed to `{DriveAPICommands._wd_cache[ctx.author.id][0]}`", inline=True)
        await ctx.send_response(embed=embed, ephemeral=True)
        
    @discord.ext.commands.slash_command(name="ls", description="List all files in your current working directory")
    async def ls(self, ctx: discord.ApplicationContext):

        if not await self._API_ready(ctx):
            return
        
        def convert_size(size_bytes):
            if size_bytes == 0:
                return "0 B"
            size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
            i = int(math.floor(math.log(size_bytes, 1024)))
            p = math.pow(1024, i)
            s = round(size_bytes / p, 2)
            return f"{s} {size_name[i]}"

        def shorten_name(name: str, folder: bool):
            if folder: name = name.rsplit(".", 1)[0]
            if len(name) < 43: return name
            else: return name[:41] + "..."
        
        folder_type_mapping = {
            True: chr(128193),
            False: chr(128196)
        }
        
        user_color = await self._get_user_color(ctx)
        
        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        
        items = self.API.search(parent=folder_id, files=True, page_size=100, recursive=True)
        items_per_page = 10
        
        item_icon_list = [f"{folder_type_mapping[item['mimeType'].startswith(self.API.FOLDER_TYPE)]} {shorten_name(item['name'], not item['mimeType'].startswith(self.API.FOLDER_TYPE))}" for item in items]
        item_size_list = [convert_size(int(item['size'])) if not item['mimeType'].startswith(self.API.FOLDER_TYPE) else "--" for item in items]
        item_kind_list = [str(guess_extension(item['mimeType']))[1:].upper() if not item['mimeType'].startswith(self.API.FOLDER_TYPE) else "Folder" for item in items]
        
        # possibly not necessary
        item_icon_list.extend([""] * (items_per_page - len(item_icon_list) % items_per_page))
        item_size_list.extend([""] * (items_per_page - len(item_size_list) % items_per_page))
        item_kind_list.extend([""] * (items_per_page - len(item_kind_list) % items_per_page))
        
        paginated_list = Paginator(
            pages=[
                discord.Embed(
                    title=f"{DriveAPICommands._wd_cache[ctx.author.id][0].name}",
                    author=discord.EmbedAuthor(name=ctx.author.name, icon_url=ctx.author.display_avatar.url),
                    description=f"Path: {DriveAPICommands._wd_cache[ctx.author.id][0]}",
                    color=user_color,
                    fields=[
                            discord.EmbedField(name="Name", value="\n".join(item_icon_list[i:i+items_per_page]), inline=True),
                            discord.EmbedField(name="Size", value="\n".join(item_size_list[i:i+items_per_page]), inline=True),
                            discord.EmbedField(name="Kind", value="\n".join(item_kind_list[i:i+items_per_page]), inline=True)
                        ]# Pycord provides a class with default colors you can choose from
                )
                for i in range(0, len(item_icon_list), items_per_page)
            ]
        )

        await paginated_list.respond(ctx.interaction, ephemeral=True)
    
    async def _get_files(ctx: discord.AutocompleteContext):
        return DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.interaction.user.id][0]]["files"]

    @discord.ext.commands.slash_command(name="download", description="Download a file from your current working directory")
    async def download(
        self, 
        ctx: discord.ApplicationContext, 
        name: discord.Option(str, "Pick a file", autocomplete=discord.utils.basic_autocomplete(_get_files)), # type: ignore
        timeout="60",
        public:bool=False
    ):

        if not await self._API_ready(ctx):
            return
        
        timeout = float(timeout)
        await ctx.response.defer(ephemeral=(not public))

        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        file = self.API.export(file_name=name, parent=folder_id, limit=ctx.guild.filesize_limit)


        user_color = await self._get_user_color(ctx)
        embed = discord.Embed(
            title=f"{name} download",
            description=f"{DriveAPICommands._wd_cache[ctx.author.id][0]}",
            color=user_color,
        )
        
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)


        if isinstance(file, str):
            embed.add_field(name="Click below for your file!", value=f"{file}\nLink expires {('<t:' + str(int(time() + timeout)) + ':R>') if timeout != float('inf') else 'never'}.", inline=True)
            if timeout != float("inf"):
                await ctx.send_followup(embed=embed, delete_after=timeout)
                await sleep(timeout)
                self.API.revoke_sharing(file[file.index("file/d/")+7:-19])
            else:
                await ctx.send_followup(embed=embed)
        else:
            @DriveAPI._temp_dir_async("temp")
            async def send_file():
                embed.add_field(name="Download the attached file!", value=f"File expires {('<t:' + str(int(time() + timeout)) + ':R>') if timeout != float('inf') else 'never'}.", inline=True)
                if timeout != float("inf"):
                    await ctx.send_followup(embed=embed, file=file, delete_after=timeout)
                else:
                    await ctx.send_followup(embed=embed, file=file)
                file.close()

            await send_file()
                
    @discord.ext.commands.slash_command(name="share", description="Share a file from your current working directory")
    async def share(
        self, 
        ctx: discord.ApplicationContext, 
        name: discord.Option(str, "Pick a file", autocomplete=discord.utils.basic_autocomplete(_get_files)), # type: ignore
        user: discord.SlashCommandOptionType.user,
        timeout="60"
    ):
        
        if not await self._API_ready(ctx):
            return
        
        timeout = float(timeout)
        await ctx.response.defer(ephemeral=True)

        folder_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        file = self.API.export(file_name=name, parent=folder_id, limit=ctx.guild.filesize_limit)

        user_color = await self._get_user_color(ctx)
        embed = discord.Embed(
            title=f"{name} has been shared with you!",
            description=f"From: {DriveAPICommands._wd_cache[ctx.author.id][0]}",
            color=user_color,
        )
        
        embed2 = discord.Embed(
            title=f"Sharing {name}",
            description=f"{DriveAPICommands._wd_cache[ctx.author.id][0]}",
            color=user_color,
        )
        
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed2.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed2.add_field(name="", value=f"File shared with {user.mention}!", inline=True)

        await ctx.send_followup(embed=embed2, ephemeral=True)

        if isinstance(file, str):

            embed.add_field(name="Click below for your file!", value=f"{file}\nLink expires {('<t:' + str(int(time() + timeout)) + ':R>') if timeout != float('inf') else 'never'}.", inline=True)
            
            if timeout != float("inf"):
                # await user.send(embed=embed, ephemeral=True, delete_after=timeout)
                await user.send(embed=embed, delete_after=timeout)
                await sleep(timeout)
                self.API.revoke_sharing(file[file.index("file/d/")+7:-19])
            else:
                # await user.send(embed=embed, ephemeral=True)
                await user.send(embed=embed)
        else:
            
            embed.add_field(name="Download the attached file!", value=f"File expires {('<t:' + str(int(time() + timeout)) + ':R>') if timeout != float('inf') else 'never'}.", inline=True)
            if timeout != float("inf"):
                # await user.send(embed=embed, ephemeral=True)
                await user.send(embed=embed, file=file, delete_after=timeout)
            else:
                await user.send(embed=embed, file=file)
            file.close()
            empty_dir("temp")
        
    
    @discord.ext.commands.slash_command(name="mkdir", description="Make a new folder in your current working directory")
    @has_permissions(administrator=True)
    async def mkdir(self, ctx: discord.ApplicationContext, folder_name: discord.SlashCommandOptionType.string):

        if not await self._API_ready(ctx):
            return

        parent_id = DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"]
        success = self.API.make_folder(file_name=folder_name, parent=parent_id)
        
        user_color = await self._get_user_color(ctx)
        embed = discord.Embed(
            title=f"Make Directory",
            color=user_color,
        )
        
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

        if success:
            embed.add_field(name="", value=f"Folder {folder_name} created at `{DriveAPICommands._wd_cache[ctx.author.id][0]}/{folder_name}`", inline=True)
            await ctx.send_response(embed=embed)
            
            folders = self.API.search(parent=parent_id, files=False, page_size=100, recursive=True)
            DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["id"] = parent_id
            DriveAPICommands._drive_state[DriveAPICommands._wd_cache[ctx.author.id][0]]["folders"] = [folder["name"] for folder in folders]
            
        else:
            embed.add_field(name="", value="Could not create folder.", inline=True)
            await ctx.send_response(embed=embed)
    
    @discord.ext.commands.slash_command(name="authenticate", description="Authenticate your google account")
    @has_permissions(administrator=True)
    async def authenticate(self, ctx: discord.ApplicationContext):
        await ctx.defer()

        embed = discord.Embed(
            title="Check your DMs!",
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

        # If the service is already initialized, do not try to reauthenticate
        if self.API.service:
            embed.title="You are already authenticated!"
            
            embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

            await ctx.respond(embed=embed)
            return

        # Generate a url for the user to visit
        flow, auth_url = self.API.generate_flow()
        if (flow, auth_url) == (None, None):
            embed.title = "credentials.json was not found or could not be processed, please ensure that you have generated the file correctly with Google Cloud and that it is in the working directory."
            embed.add_field(name="", value="[Google Drive Developer quick-start instructions](https://developers.google.com/drive/api/quickstart/python)")
            response = await ctx.respond(embed=embed)
            return
            

        # Tell the user to check their dms
        response = await ctx.respond(embed=embed)
        
        # DM the user to visit the url
        await ctx.author.send(f'Please go to [this URL]({auth_url}) and respond with the authorization code.')

        # Function that validates that a message is from the author and in the DM channel
        def check(m: discord.Message):
            return isinstance(m.channel, discord.DMChannel) and m.author == ctx.author

        # Wait for a response
        msg = await self.bot.wait_for("message", check=check)
        
        # Authenticate the token that was provided by the user
        flow.fetch_token(code=msg.content)
        creds = flow.credentials
        
        # Generate new credentials
        with open("token.json", "w") as token:
            token.write(creds.to_json())

        # Initialize the service
        self.API.create_service(creds)

        # Respond that authentication is complete
        embed.title = "Authentication Complete!"
        await ctx.author.send(embed=embed)
        await response.edit(embed=embed)
        
        if self.API.service is not None:
            items = self.API.search(parent=self.API.ROOT_ID, page_size=100, recursive=True)
            DriveAPICommands._drive_state[self.root_path]["id"] = self.API.ROOT_ID
            DriveAPICommands._drive_state[self.root_path]["folders"] = [folder["name"] for folder in items if folder['mimeType'].startswith(self.API.FOLDER_TYPE)]
            DriveAPICommands._drive_state[self.root_path]["files"] = [file["name"] for file in items if not file['mimeType'].startswith(self.API.FOLDER_TYPE)]
    
    @discord.ext.commands.slash_command(name="discord_drive_commands", description="Show all useable commands")
    async def help(self, ctx: discord.ApplicationContext):
        user_color = await self._get_user_color(ctx)
        embed = discord.Embed(
            title=f"Commands List",
            color=user_color,
        )
        
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        for text in "`/authenticate`: Regenerates the token needed to enable the API. If re-authentication is needed, the bot will DM the caller a link and wait for the authentication code given to the caller by Google\n`/cd <directory>`: Navigates the caller down into a child directory of their current directory. Autocomplete is provided for hints.\n`/download <file> <timeout (optional)> <public (optional)>`: Gives the user the file (or a link) to download the file specified. Files have autocomplete. Timeout defaults to 60 seconds, where the file will then no longer be allowed to be downloaded. Public defaults to False, where no other users can see the file.\n`/ls`: Shows the caller the contents of their current directory.\n`/pwd`: Shows the caller the file path of their current directory.\n`/share <file> <user> <timeout (optional)>`: Sends a specified server member a dm with a file from the caller's current directory. Files and users have autocomplete. Timeout defaults to 60 seconds, where the file will then no longer be allowed to be downloaded.\n`/upload <attachment>`: Uploads a file or zip file to the caller's current directory. Zip files must contain just the files, and no folders, as they will not be read.".split("\n"):
            embed.add_field(name="", value=text, inline=False)
        await ctx.send_response(embed=embed)
        
