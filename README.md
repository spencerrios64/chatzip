# chatzip

Turn your AI data exports into one tidy zip: a folder per AI, a text file per chat.

**Use it here: https://spencerrios64.github.io/chatzip/**

```
ai-chats.zip
├─ Claude/
│   ├─ 2026-11-01 Godot help.txt
│   └─ ...
├─ ChatGPT/
├─ Gemini/
├─ Grok/
└─ DeepSeek/
```

It is a single web page (`index.html`) with no dependencies and no server. Your files
are read in your browser and never uploaded. Works on desktop and on Android.

## Use

1. In each AI's settings, request a data export and download the file it sends you.
2. Open the page (link above, or `index.html`), pick all the export files at once.
3. Press **Download zip**.

By default each text file holds only your own messages. Tick **Also include the AI's
replies** to get the whole conversation.

## What it can and can't do

- It reads export files. It cannot log in to your accounts or fetch chats by itself;
  the AI services don't offer a way to do that.
- **Claude** and **ChatGPT** exports are tested (on small sample exports).
- **Gemini**, **Grok** and **DeepSeek** are supported from their documented formats and
  have not been checked against real exports. Open an issue if yours doesn't load.
- Gemini: use Google Takeout, select **My Activity > Gemini Apps**, and switch the
  format from HTML to **JSON**. Google doesn't group prompts into chats, so you get
  one file per day.
- Exports over 4 GB (zip64) aren't supported: unzip them and pick the `.json` inside.
- The zip contains your private chats. Keep it somewhere safe.

A [chatvault](https://github.com/spencerrios64/chatvault) archive (`export --format archive`)
can be picked too.
