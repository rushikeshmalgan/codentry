# Codentry — Project Update (abhi tak kya hua hai)

**Kis ke liye likha hai:** team ke un members ke liye jinhe pichle kaam ka pata nahi hai.
**Date:** 2 October 2026. **Latest commit:** `2f38f58` (pushed on GitHub, `main` branch, CI green — matlab automated tests pass ho rahe hain).
**Agar kuch samajh na aaye:** neeche "Important files" section mein poore detail wale docs hain, ya group mein pooch lena.

---

## 1. Codentry hai kya (the idea)

Shuru mein idea simple tha: **ek GitHub App jo pull request (PR) aate hi usko review kare** — ESLint/Semgrep (deterministic static analysis tools) se code check kare, **aur Claude AI se bhi review karwa ke** ek saath comment post kar de PR pe.

**Lekin beech mein hum ne socha aur direction badal di.** Reason simple tha: agar hum sidha AI ko PR review karne de dete bina yeh check kiye ki AI actually sahi/useful findings de raha hai ya nahi, to woh sirf ek "demo" ban jata — kaam ka proof nahi hota. Research/FYP ke point of view se yeh weak hota. Isliye humne socha:

> Pehle ek **"evidence-first" system** banao jo differential static analysis kare (yaani sirf PR ne jo NAYA code add kiya hai uske findings dikhaye, purana code ka noise nahi), aur phir ek **evaluation harness** (measurement system) banao jo test kare ki static analysis aur AI dono kitna accurate hain, kitna overlap karte hain, kitna galat (noise) bolte hain — **real data pe, real numbers ke saath**.

Matlab: **AI ab is project ka "main feature" nahi hai — woh ek optional signal hai jisko hum measure karenge**, use karne se pehle. Main contribution ab yeh hai: ek solid, tested static-analysis pipeline + ek research-grade evaluation system jo honestly batata hai ki kya kaam karta hai aur kya nahi.

Yeh pivot (direction change) poora documented hai `docs/WHAT_CHANGED.md` mein — original PRD abhi bhi wahi hai jo pehle tha, hum ne woh edit nahi kiya, balki ek naya reasoning document banaya jisme likha hai ki humne kya aur kyun badla.

---

## 2. Ab tak kya ban chuka hai (step by step)

### Phase 0 — Foundation hardening (security + reliability)
Yeh sabse pehla kaam tha, bina kisi AI ke. Isme humne:
- Security holes fix kiye (jaise: PR wala malicious ESLint config load ho sakta tha, jo RCE — remote code execution — tak ja sakta tha; ab PR ka config kabhi trust nahi karte).
- Webhook aur background job system ko **durable** banaya — matlab agar server crash ho jaye ya request do baar aa jaye, to kaam duplicate nahi hoga ya lost nahi hoga.
- **Differential analysis** banaya: PR ke `base` (purana) aur `head` (naya) dono version ko analyze karke sirf woh findings dikhate hain jo PR ne naye introduce kiye — purane bugs ka blame PR ko nahi dete.
- Finding ki "identity" line-number pe based nahi hai — matlab agar PR sirf upar kuch lines add kare (jisse neeche sab kuch shift ho jaye), to same problem ko dobara "naya" nahi bolenge.
- Yeh sab **committed aur tested hai**, real ESLint/Semgrep ke saath (mock nahi).

### 8-Day Evaluation Plan (Days 1–6 done)
Phase 0 ke baad, ek 8-din ka plan bana (`docs/8_DAY_IMPLEMENTATION_PLAN.md`) jisse evaluation system banaya gaya:

- **Day 1:** Basic evaluation harness — ek "case" format banaya (ek case = ek chhota sa code change + uska sahi/galat defect kaha hai yeh pata), Arm A (static analysis arm) ka runner, matching logic (finding sahi jagah pe hai ya nahi check karna), stats tools (Wilson confidence interval — chhote sample size pe result kitna reliable hai yeh batata hai).
- **Day 2:** **169 "mutation" test cases** banaye — real open-source code (jaise validator.js, uuid, minimist) lekar, usme ek choti si galti seed ki (jaise `<` ko `<=` bana diya) — taaki pata ho ki yeh defect hai aur kahan hai.
- **Day 3:** **30 real bugs** liye BugsJS dataset se (Express, Karma, ESLint, Hexo jaise real projects ke actual fixed bugs), aur **36 real merged pull requests** liye (fastify, axios, zod se) jisse "noise" measure kar sake (kitne findings aate hain normal PR pe). Saath mein ek **labeling protocol** banaya — do alag team members ek finding ko dekh ke bolenge "yeh real issue hai ya nahi" — **yeh kaam AI/model kabhi nahi karega**, kyunki model khud ko judge nahi kar sakta.
- **Day 4:** **Asli run kiya — 237 cases pe Arm A (static analysis) chalaya.** Pehli baar real numbers mile (neeche section 3 mein dekho).
- **Day 5:** AI arm (Claude) banane ka plan tha, lekin **condition thi ki pehle labeling ho chuki ho aur ek paid API key ho** — dono abhi available nahi hain, to yeh step **pause** hai, abandon nahi. Design + cost estimate already ban chuka hai (`docs/AI_ARM_DESIGN_AND_COST.md`), jab budget/labeling ready ho to turant implement ho sakta hai.
- **Day 6:** Do arms (static + AI) ko compare karne wala tool bana diya (overlap, statistical test), lekin AI arm abhi nahi hai to woh sirf "plan" dikhata hai, fake numbers nahi banata. Real GitHub/Supabase/Render/Vercel pe deploy karke test karna bhi iska part tha — **yeh nahi hua kyunki iske liye accounts chahiye** (GitHub App register karna, Supabase project banana, etc.) jo abhi kisi ke paas nahi hain.
- **Day 7/8 (draft):** Demo script, Q&A prep, aur final results likhe ja chuke hain — lekin actual rehearsal/presentation team ko karna hai.

---

## 3. Real results kya mile (yeh interesting hai)

Jab humne static analysis (ESLint + 6 Semgrep rules) ko 237 real cases pe chalaya:

| Kis type ke bugs pe | Kitne cases | Pakda kitna % |
|---|---|---|
| Seed kiye hue logic bugs (jaise `<` ko `<=`) | 129 | **sirf 1.6%** |
| Real bugs (BugsJS se) | 30 | **sirf 3.3%** |
| Security-type patterns (`eval()`, hardcoded password, etc.) | 39 | **100%** |

**Yeh low number koi failure nahi hai — yeh expected tha aur plan mein pehle hi likha gaya tha** ki "ek chhoti si 6-rule wali ruleset semantic/logic bugs nahi pakad payegi." Matlab: static analysis tools sirf **pattern-based** cheezein pakadte hain (jaise `eval()` use karna khatarnak hai), par woh samajh nahi sakte ki "yahan loop ek extra baar chal raha hai" — isliye AI ki zaroorat hai, lekin **usko bhi measure karna padega** ki woh actually better hai ya nahi, usi tarah se.

Ek aur achi cheez: humne check kiya ki agar PR sirf lines shift kare (jaise upar blank lines add kar de) ya sirf whitespace change kare, to kya same problem ko dubara "naya finding" bolta hai — **877 out of 877 real findings ne apni identity maintain ki**. Matlab yeh system sach mein samajhta hai "same problem" vs "line number change hua hai bas."

Sab kuch `evaluation/reports/2026-10-02-arm-a.md` mein detail mein hai, aur dubara run karne se bilkul same result aata hai (reproducible).

---

## 4. Completion % — kitna kaam hua hai

Yeh do tarike se dekh sakte hain, dono sahi hain, bas alag baseline pe:

### (A) Jo abhi hum actually bana rahe hain (evidence-first + evaluation) → **~90% complete**
Isme sab kuch jo plan kiya tha (harness, 3 alag dataset, real run, real report, stability check) **ban chuka hai**. Bacha hua kaam sirf **human steps hain, code nahi**:
- Team ke 2 logon ko ~40 findings label karna hai (2-3 ghante ka kaam, instructions already ready hain).
- Demo rehearse karna.
- (Optional) Agar budget mile to AI arm banana.

### (B) Original PRD ke against (jisme AI review + PR pe comment post karna tha) → **~40-50% complete**
Yeh kam isliye hai kyunki humne **jaanbhoojh kar** AI review aur comment-posting ko pause kiya — bina measure kiye AI ko production mein daalna risky/galat approach tha. Infra aur static analysis wala part done hai, AI wala part deliberately deferred hai.

**Important:** yeh koi "hum peeche hain" wali baat nahi hai — yeh ek soch samajh kar liya gaya decision hai, jo documented hai. Jab koi poochhe "AI kahan hai project mein?" to yeh explain kar sakte ho.

---

## 5. Abhi kya baaki hai (team action items)

| Kaam | Kisko karna hai | Kitna time |
|---|---|---|
| ~40 findings label karna (real issue / not an issue / unclear) | 2 team members, independently | ~2-3 hours total |
| GitHub App + Supabase + Render + Vercel account banake real deployment test karna | Jisko bhi account access mile | Ek baar ka setup |
| AI arm banana (agar paisa mile — Claude API ka) | Budget decide karna | $1-70 range, model pe depend karta hai |
| Demo rehearse karna (2 baar) + backup recording | Poori team | Demo ke pehle |

**Koi bhi labeling ya "yeh finding sahi hai ya galat" wala decision AI/model se nahi karwana hai** — yeh rule hai, kyunki agar AI apne aap ko judge kare to result biased ho jayega.

---

## 6. Important files (zyada detail ke liye)

| File | Kya hai isme |
|---|---|
| `docs/PROJECT_STATUS.md` | Sabse detailed, up-to-date technical status (English mein) |
| `docs/FINAL_RESULTS.md` | Real numbers + unki limitations, threats to validity |
| `docs/8_DAY_IMPLEMENTATION_PLAN.md` | Din-wise plan + har din ka status note |
| `docs/AI_ARM_DESIGN_AND_COST.md` | AI arm ka design + cost estimate (jab implement karenge) |
| `docs/REAL_RUN_LOG.md` | Real deployment (GitHub/Supabase/etc.) abhi kyun nahi hua |
| `docs/DEMO.md` | Demo ka script/outline |
| `docs/QA_PREP.md` | Likely questions aur unke jawab (jaise "AI kahan hai?") |
| `evaluation/README.md` | Evaluation harness kaise chalayein, sab commands |
| `evaluation/labeling/protocol.md` | Labeling kaise karni hai, step by step |

---

## 7. Quick FAQ (jo teammates pooch sakte hain)

**Q: Yeh "AI project" hai na? AI kahan hai?**
A: AI abhi optional/future part hai. Project ka main contribution static analysis + uska honest evaluation hai. AI design ready hai, bas budget/labeling ka wait hai.

**Q: Humne itna kaam kiya but static analysis sirf 1.6-3.3% bugs pakad raha hai, yeh to bura lagta hai?**
A: Yeh number hi to important finding hai — isi liye hum measure kar rahe the. Agar hum bina measure kiye keh dete "humara tool bugs pakadta hai" to woh galat claim hota. Ab humare paas proof hai ki simple static rules kaafi nahi hote, aur AI arm (jab banega) ko isi baseline se compare karenge.

**Q: Real GitHub pe test kyun nahi kiya?**
A: Kisi ke paas abhi GitHub App, Supabase, Render, Vercel ka account nahi hai is project ke liye. Jab milega, ek ready-made step-by-step guide hai follow karne ke liye.

**Q: Code kahan hai?**
A: `github.com/rushikeshmalgan/codentry`, `main` branch, latest commit `2f38f58`. CI (automated tests) green hai.
