from inspect import getfullargspec

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from discord import Attachment, File, ApplicationContext, Client, Message, DMChannel, Embed
from zipfile import ZipFile, BadZipFile
from mimetypes import guess_type
from io import BytesIO, open
from datetime import datetime, timedelta

from ._utils import *

class DriveAPI:
    ROOT = ""
    ROOT_ID = ""
    
    folders = dict()

    service = None

    FOLDER_TYPE = "application/vnd.google-apps.folder"
    SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.activity", "https://www.googleapis.com/auth/drive.metadata"]

    def _input_validator(func):
        def _validate(self, *args, **kwargs):
            """Loops across all args and kwargs and validates that annotated arguments received the expected type,
            as well as validating that no arguments are None.
            """
            argspecs = getfullargspec(func)
            annotations = argspecs.annotations
            argnames = argspecs.args
            for val, arg in zip(args, argnames[1:len(args) + 1]):
                assert val is not None, f"Argument '{arg}' is None, please do not use None as an argument"
                if arg in annotations:
                    assert isinstance(val, annotations[arg]), f"Argument '{arg}' is not of the type '{str(annotations[arg])[8:-2]}'."
            for arg in kwargs:
                assert kwargs[arg] is not None, f"Argument '{arg}' is None, please do not use None as an argument."
                if arg in annotations:
                    assert isinstance(kwargs[arg], annotations[arg]), f"Argument '{arg}' is not of the type '{str(annotations[arg])[8:-2]}'."
            return func(self, *args, **kwargs)    
        return _validate
    
    def _temp_dir_async(path):
        def _temp_decorator(func):
            async def _temp_manager(*args, **kwargs):
                """Wraps an asynchronous functon. Creates an empty temporary directory before the function,
                calls the function, and then clears and removes the temporary directory.
                """
                if not os.path.exists(path):
                    os.mkdir(path)
                else:
                    try:
                        empty_dir(path)
                    except Exception as e:
                        pass
                ret = await func(*args, **kwargs)
                try:
                    empty_dir(path)
                    os.rmdir(path)
                except Exception as e:
                    pass
                return ret
            return _temp_manager
        return _temp_decorator
    
    def _temp_dir(path):
        def _temp_decorator(func):
            def _temp_manager(*args, **kwargs):
                """Wraps a synchronous functon. Creates an empty temporary directory before the function,
                calls the function, and then clears and removes the temporary directory.
                """
                if not os.path.exists(path):
                    os.mkdir(path)
                else:
                    try:
                        empty_dir(path)
                    except Exception as e:
                        pass
                ret = func(*args, **kwargs)
                try:
                    empty_dir(path)
                    os.rmdir(path)
                except Exception as e:
                    pass
                return ret
            return _temp_manager
        return _temp_decorator


    @_input_validator
    def __init__(self, root:str):
        """Initializes the DriveAPI object by starting the service if possible

        Args:
            root (str): Root folder to connect to

        Raises:
            Exception: If the root directory is an empty string
        """
        # Root directory must be real
        if not root:
            raise Exception("A root directory must be provided.")
        self.ROOT_ID = root.rsplit("/",1)[1].split("?resourcekey=")[0]
        
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists("token.json"):
            try:
                creds = Credentials.from_authorized_user_file("token.json", self.SCOPES)
            except:
                creds = None
        # If there are no (valid) credentials available, attempt to do it for them.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open("token.json", "w") as token:
                        token.write(creds.to_json())
                    self.create_service(creds)
                except:
                    pass
        # if creds are good, build the service
        else:
            self.create_service(creds)

    def generate_flow(self):
        if not os.path.exists("credentials.json"):
            return None, None
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.SCOPES,
                    redirect_uri='urn:ietf:wg:oauth:2.0:oob'
                )
            
            auth_url, _ = flow.authorization_url(prompt='consent', )
            return flow, auth_url
        except:
            return None, None

    @_input_validator
    def create_service(self, creds: Credentials):
        try:
            self.service = build("drive", "v3", credentials=creds)

            folder = self.service.files().get(fileId=self.ROOT_ID).execute()
            
            if not folder:
                raise Exception("No folders found, check the root name.")
            self.ROOT = folder["name"]
            self.ROOT_ID = folder["id"]
            self.folders[folder['name']] = folder['id']
            print(f"Found folder '{folder['name']}' with id '{folder['id']}'")
        except HttpError as error:
            # TODO(developer) - Handle errors from drive API.
            print(f"An error occurred: {error}")


    @_input_validator
    def update_folders(self, flist:list) -> None:
        for file in flist:
            if file["mimeType"] == self.FOLDER_TYPE:
                self.folders[file["name"]] = file["id"]
    
    @_input_validator
    def search(self, file_name:str='', parent:str='', page_size:int=1, files:bool=True, folders:bool=True, page_token:str='', recursive:bool=False) -> list:
        """Modular search function that can find files and folders, with the option of a specified parent directory.

        Args:
            file_name (str, optional): Name of a specific file/folder to find. Defaults to ''.
            parent (str, optional): Name of a parent folder to search inside of. Defaults to ''.
            page_size (int, optional): Number of results to return. Defaults to 1.
            files (bool, optional): Enable searching for files. Defaults to True.
            folders (bool, optional): Enable searching for folders. Defaults to True.
            pageToken (str, optional): Token for the next page of results. Defaults to ''.
            recursive (bool, optional): Search all pages for all results. Defaults to False.

        Raises:
            Exception: Any input parameters are None
            Exception: Both the name and parent fields are left blank

        Returns:
            list(dict): A list of the files found. Format: [{'mimeType': 'application/vnd.google-apps.folder', 'id': '1FkOWqVDhbj8y5N7gq7-XQqQjCceMVLN9', 'name': 'Example'},...]
        """
        
        # Generate the search parameter for a file name
        nameScript = f" and name = '{file_name}'" if file_name else ""

        # Generate the search parameter for a parent folder
        try:
            parentScript = f" and '{parent}' in parents" if parent else ""
        except HttpError as error:
            print(f"The parent folder does not exist: {error}")
            return None, None
        
        if nameScript == parentScript:
            raise Exception("Both parameters cannot be empty.")
        
        if files and folders:
            mimeScript = ""
        elif files:
            mimeScript = f"and mimeType!='{self.FOLDER_TYPE}'"
        else:
            mimeScript = f"and mimeType='{self.FOLDER_TYPE}'"

        try:
            results = (
                self.service.files()
                .list(pageSize=page_size, 
                    pageToken=page_token, 
                    q=f"trashed = false{mimeScript}{nameScript}{parentScript} and mimeType!='application/vnd.google-apps.shortcut'",
                    orderBy="folder, name", 
                    fields="nextPageToken, files(id, name, mimeType, size)")
                .execute()
            )
            foundfiles = results.get("files", [])
            self.update_folders(foundfiles)
            if (page_token := results.get("nextPageToken", "")) and recursive:
                return foundfiles + self.search(file_name=file_name, page_size=page_size, parent=parent, files=files, folders=folders, page_token=page_token, recursive=recursive)
            return foundfiles
        except HttpError as error:
            print(f"An error occurred: {error}")
            return None

    @_temp_dir_async("temp")
    @_input_validator
    async def upload_from_discord(self, file:Attachment, parent:str=""):
        file_name = f"temp/{file.filename}"
        await file.save(file_name)
        try:
            if 'zip' not in guess_type(file_name)[0]: raise BadZipFile
            with ZipFile(file_name, 'r') as zf:
                zf.extractall("temp")
            os.remove(file_name)
            flist = [self.upload(file_name, mimetype, local_path="temp", parent=parent) for file_name in os.listdir("temp") if (mimetype := guess_type(os.path.join("temp", file_name))[0]) is not None]
            if len(flist) != len(os.listdir("temp")):
                s = "Please ensure that there are no folders inside of the zip file, as they and their contents will not be uploaded.\n"
                if len(flist) == 0:
                    return s.strip()
            else: s = ""
            return f"{s}File{'s' if len(flist) != 1 else ''} `{', '.join(flist)}` uploaded!"
        except BadZipFile:
            return f"File `{self.upload(file.filename, file.content_type, local_path='temp', parent=parent)}` uploaded!"
            
    
    @_input_validator
    def upload(self, file_name:str, content_type:str, local_path:str=".", parent:str=""):
        if not parent:
            parent = self.ROOT
        
        file_metadata = {
            "name": file_name[:min(len(file_name), 100)],
            "mimeType": content_type,
            "parents": [parent]}
        
        media = MediaFileUpload(local_path + "/" + file_name, mimetype=content_type)
        
        try:
            file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="name")
                .execute()
            )
            return file["name"]
        except HttpError as error:
            print(f"An error occurred: {error}")
            return None

    @_input_validator
    def make_folder(self, file_name:str, parent:str=""):
        if not parent:
            parent = self.ROOT
        
        file_metadata = {
            "name": file_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent]
        }
        try:
            file = (
                self.service.files()
                .create(body=file_metadata, fields="id")
                .execute()
            )
            self.folders[file_name] = file["id"]
            return True
        except HttpError:
            return False
    
    @_temp_dir("temp")
    @_input_validator
    def export(self, file_name:str, parent:str="", limit:int=8388608):
        if not parent:
            parent = self.ROOT
        
        file = self.search(file_name=file_name, parent=parent, folders=False)
        if not file:
            return "File not found."

        file_id = file[0]["id"]

        if int(file[0]['size']) >= limit:
            permissions = {
                'type': 'anyone',
                'role': 'reader',
                "expirationTime": (datetime.now() + timedelta(minutes=2)).astimezone().isoformat()
            }
            
            self.service.permissions().create(fileId=file_id, body=permissions).execute()

            return f'[{file_name}](<https://drive.google.com/file/d/{file_id}/view?usp=sharing>)'


        try:
            # pylint: disable=maybe-no-member
            request = (
                self.service.files()
                .get_media(fileId=file_id)
            )
            file = BytesIO()
            downloader = MediaIoBaseDownload(file, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                # print(f"Download {int(status.progress() * 100)}.")
            filepath = os.path.join("temp", file_name)
            with open(filepath, "wb") as f:
                file.seek(0)
                f.write(file.read())

            fileObj = file = File(filepath)
            return fileObj
        
        except HttpError:
            return "An error occured retrieving this file."
        
    def revoke_sharing(self, file_id:str):
        self.service.permissions().delete(fileId=file_id, permissionId="anyoneWithLink").execute()



if __name__ == "__main__":
    API = DriveAPI("Textbooks")
    # print("\n".join([f"{result['name']} is of type {result['mimeType']} with ID {result['id']} and size {result['size']}" for result in API.search(page_size=100, folders=False, parent=API.ROOT_ID)]))
    print(API.export("15L2SwoxFWUtcK6lNbblGMWOvI4qgW68E"))