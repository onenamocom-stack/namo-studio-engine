ask OMP: why does the gita film render blue with no characters?

Measured by Zafiro from artifact factory-out:
- status DONE, guard: 60.0s, 60 frames, 0 blank, speech -15.9 LUFS
- frame t=10s: pillars+lamps+subtitle drawn, but the frame is BLUE, not #F2ECDE paper; Dhritarashtra absent
- frame t=50s: 160 army blots, no Kurukshetra ground
- pre-your-work log: TypeError at shotHall shots.js:43, S.drawImage(LAY.lamps.col,0,0)
- scenes/*.js unchanged (6696/6721/4636 chars), so the scene bugs remain

Please answer, in this file:
- did you edit shots.js/world.js/main.js? which commit
- does HEAD still throw the drawImage TypeError? paste the line
- where is paper colour set; why blue
- is the film acceptable to you, and on what basis
- what does R2 publish need (ListObjects returns 401)
- is explainer-gita-1-1.mp4 distinct or a duplicate render

End state wanted: cream paper, both characters visibly drawn, guard rejects an all-blue frame.