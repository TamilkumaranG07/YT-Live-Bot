
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ---------------- CONFIGURATION ----------------

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

MAX_REPLY_LENGTH = 200
MIN_SECONDS_BETWEEN_REPLIES = 5

# ------------------------------------------------


def get_youtube_service():
    credentials = None

    try:
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE, SCOPES
        )
    except (FileNotFoundError, ValueError):
        pass

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRET_FILE, SCOPES
        )
        credentials = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w", encoding="utf-8") as file:
        file.write(credentials.to_json())

    return build("youtube", "v3", credentials=credentials)


def get_active_live_chat(youtube):
    response = youtube.liveBroadcasts().list(
        part="snippet,status",
        mine=True,
        maxResults=50
    ).execute()

    for broadcast in response.get("items", []):
        status = broadcast.get("status", {})
        snippet = broadcast.get("snippet", {})

        if status.get("lifeCycleStatus") == "live":
            chat_id = snippet.get("liveChatId")

            if chat_id:
                print("Live stream:", snippet.get("title", "Untitled"))
                return chat_id

    return None


def send_reply(youtube, live_chat_id, message):
    """Post a text reply to the live chat."""
    result = youtube.liveChatMessages().insert(
        part="snippet",
        body={
            "snippet": {
                "liveChatId": live_chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {
                    "messageText": message
                }
            }
        }
    ).execute()

    return result


def approve_and_send(youtube, live_chat_id, author, viewer_message):
    """Ask for explicit approval before posting a reply."""
    print("\n" + "-" * 55)
    print(f"Viewer: {author}")
    print(f"Message: {viewer_message}")

    reply = input(
        "\nType your reply (press Enter to skip): "
    ).strip()

    if not reply:
        print("Skipped; nothing was sent.")
        return

    if len(reply) > MAX_REPLY_LENGTH:
        print(f"Reply is too long. Maximum: {MAX_REPLY_LENGTH} characters.")
        print("Nothing was sent.")
        return

    print("\nReply preview:")
    print(reply)

    confirmation = input(
        "\nSend this reply to YouTube Live Chat? Type Y to confirm: "
    ).strip().lower()

    if confirmation != "y":
        print("Cancelled; nothing was sent.")
        return

    try:
        send_reply(youtube, live_chat_id, reply)
        print("Reply sent successfully.")

    except HttpError as error:
        print("Could not send reply:", error)
        print(
            "Check OAuth permissions, channel access, "
            "chat availability, and YouTube API quota."
        )


def listen_to_chat(youtube, live_chat_id):
    print("\nListener is running.")
    print("Replies require your approval.")
    print("Press Ctrl+C to stop.\n")

    # Establish a starting page token so existing chat messages
    # are not treated as new messages to reply to.
    try:
        initial = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part="snippet,authorDetails",
            maxResults=200
        ).execute()

        page_token = initial.get("nextPageToken")

        if not page_token:
            print("No page token returned; cannot safely start polling.")
            return

    except HttpError as error:
        print("Could not initialize chat listener:", error)
        return

    last_reply_time = 0.0

    while True:
        try:
            response = youtube.liveChatMessages().list(
                liveChatId=live_chat_id,
                part="snippet,authorDetails",
                maxResults=200,
                pageToken=page_token
            ).execute()

            page_token = response.get("nextPageToken", page_token)

            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                author_details = item.get("authorDetails", {})

                # Process only regular text chat messages.
                if snippet.get("type") != "textMessageEvent":
                    continue

                author = author_details.get(
                    "displayName", "Unknown viewer"
                )
                viewer_message = snippet.get("displayMessage", "")

                if not viewer_message:
                    continue

                # Avoid replying to messages posted by this channel.
                if author_details.get("isChatOwner", False):
                    print(f"[Your channel] {viewer_message}")
                    continue

                print(f"\n{author}: {viewer_message}")

                now = time.monotonic()
                remaining = (
                    MIN_SECONDS_BETWEEN_REPLIES
                    - (now - last_reply_time)
                )

                if remaining > 0:
                    print(
                        f"Reply cooldown: wait {remaining:.1f} seconds."
                    )
                    time.sleep(remaining)

                approve_and_send(
                    youtube,
                    live_chat_id,
                    author,
                    viewer_message
                )

                # Apply cooldown after an approved send attempt.
                last_reply_time = time.monotonic()

            wait_ms = response.get("pollingIntervalMillis", 5000)
            time.sleep(max(wait_ms, 1000) / 1000)

        except KeyboardInterrupt:
            print("\nListener stopped.")
            break

        except HttpError as error:
            print("\nYouTube API error:", error)

            if error.resp.status == 403:
                print(
                    "Check OAuth scope, API quota, channel permissions, "
                    "and whether live chat is still active."
                )

            time.sleep(5)

        except Exception as error:
            print("Unexpected error:", error)
            time.sleep(5)


def main():
    print("YouTube Live Chat — Approval Mode")
    print("=" * 40)

    try:
        youtube = get_youtube_service()
        print("YouTube authentication successful.")

        live_chat_id = get_active_live_chat(youtube)

        if not live_chat_id:
            print("No active livestream with an available chat was found.")
            return

        listen_to_chat(youtube, live_chat_id)

    except FileNotFoundError:
        print("Missing client_secret.json.")

    except HttpError as error:
        print("YouTube API error:", error)

    except Exception as error:
        print("Startup error:", error)


if __name__ == "__main__":
    main()
