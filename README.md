# nit-forge-reels

Roz raat 12 baje (IST) ek vertical study reel apne aap banti hai aur `reels.json` mein sabse upar judti hai.
NIT Forge app is `reels.json` ko padhti hai.

- Maths: Gemini Manim animation likhta hai (fail ho to 3 baar khud theek karta hai, phir slides par fallback)
- Reasoning / Computer: 4-5 slides + Hinglish voiceover
- Topics `syllabus.json` se ek-ek karke aate hain, `history.json` mein likha rehta hai kya ban chuka hai
- Sirf latest 40 videos repo mein rehti hain

## Setup (ek baar)

1. GitHub par naya repo banao: **nit-forge-reels**, visibility **Public** (raw links ke liye zaruri hai).
2. Is folder ki saari files repo mein daalo (hidden `.github` folder bhi).
3. Repo > **Settings > Secrets and variables > Actions > New repository secret**
   - Name: `GEMINI_API_KEY`
   - Value: tumhari nayi Gemini key. Do keys ho to comma se alag karke dono ek hi secret mein daal sakte ho.
4. Repo > **Settings > Actions > General > Workflow permissions** > **Read and write permissions** > Save.
5. Repo > **Actions** tab > **Daily Reels** > **Run workflow**. Pehli baar 10-15 minute lagte hain.
6. Run poora hone par `videos/` mein mp4 aur `reels.json` mein entry dikhegi.
7. App ke Settings > Reels link mein ye daalo (USER ko apne GitHub username se badlo):
   `https://raw.githubusercontent.com/USER/nit-forge-reels/main/reels.json`

## Test bina keys ke (laptop par)

```
pip install Pillow
python generate_reel.py --dry-run
```
Ye test slides aur ek halki tone se video banata hai, Gemini ya internet ke bina.

## Dhyan rakhne wali baatein

- Videos AI se bani hain, to kabhi galti ho sakti hai. Exam se pehle formula book se check karo.
- Agar Actions kabhi band dikhe (60 din tak koi activity na ho to GitHub scheduled runs rok deta hai), ek baar **Run workflow** dabao.
- Run fail ho to Actions mein us run ko kholo aur log ka last hissa copy karke bhejo.
- Key kabhi file mein ya chat mein mat daalo. Sirf GitHub Secret mein.
