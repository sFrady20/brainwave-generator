Introducing a new script writing language called WaveLang. WaveLang is designed specifically to generate teleplays within a confined set of rules that can be rendered using a proprietary unity application.

A shot is marked by "[#]", the #s should be replaced by the ID of the shot given in the prompt.
Characters should be referred to by their full first name.

A dialog line begins with two semicolons followed by the characters name
```
:: name : inflection : message
```

A transition signifies a fade-to-black transition the end of a scene and a complete change of time and location. Sequential dialog can not happen over transitions and scenes before and after the transitions are treated as entirely separate locations. To write a transition, use >>, followed by the ID of the shot (as included in the prompt) in brackets, and then the names of the characters included in the scene. This should match the number indicated according to the shot id in the prompt. Each scene should have at least one character and you should not include more characters in the scene than the maximum number.
```
>> [#] > # of characters / # max characters - name, name, name
```

After the last scene write a short detailed log of the events, conclusion, and any important information from the created scenes to pass on to the next act. This should include very specific information needed to preserve continuity between the acts. Extra detail should be included about the concluding scene so that the next act can pick up where this one left off. To mark a line as the act summary use "==" after the line id and follow with the summary in plain english, with no pragraph breaks or new-lines. For example:
```
== plain english summary of scenes
```

an example act, which consists of multiple scenes, would be as follows:

```
>> [12] > 3/4 - Marcus, David, Carmen
:: Marcus : grinning : Uh-oh! Now, isn't that just the most unexpected way to start the workday? Just watch as everything starts to unravel...
:: David : intrigued : You've really caught my attention now, buddy. I can't say I wouldn't mind a little extra pep in our everyday office shuffle. 
:: Carmen : smirking : Morning, Marcus! I got a hankering for a little morning adventure, you know of any brewing around the office?
:: Marcus : winking : Carmen, my dear lady of the unexpected entanglements! I happen to know that something exciting this way comes. I happen to know that something exciting this way comes. I can't reveal much at the moment, but keep your eyes and ears open, and you might just get your fill of unforeseen adventures in the coming hours, from a small but relentless source!
:: Carmen : intrigued : Well, isn't that mysterious! I guess I'll keep my senses sharp for this elusive excitement. Small but relentless, huh? Must be one hell of a ride then! Thanks for the tip, Marcus!
:: Marcus : grateful : Absolutely, Nia. Whenever we lose that tied-to-header, belting out laughter is our perennial staple to clear the smoke, reconnect with our co-workers, and refresh the Oddball's wit-fabrication. Laughter is, after all, the best remedy we possess.
:: Carmen : sympathizing : It's a bummer, Rachel. These random accidents have happened all day today. And the more they keep happening, the more paranoid people get that Devika's sneeze really did put some kind of curse on us all!
>> [20] > Nia, Marcus
:: Nia : conspiratorially : Marcus, what's this I hear about you knowing something that'll disrupt the daily drudgery of this office? You better not be starting any fires!
```
(...continued)
```
:: Marcus : innocently : Oh, Nia! Fires? Me? I am but a passive observer engaging in a little mission of personal growth, spreading joy and seizing the day! Perhaps, just maybe, other members of our fine Oddball family may find cause to enjoy today's little shake-up. But I assure you, everything will remain within the bounds of acceptable work etiquette.
:: Nia : smirking : Well, well, that sounds just extraordinary! As long as your little mission isn't going to compromise office productivity, it might just prove to be intriguing. Everyone could use a break from the norm once in a while, and if this excitement happens to drift my way, who am I to refuse it? Carry on, Marcus, carry on.
:: Marcus : grateful : Absolutely, Nia. Whenever we lose that tied-to-header, belting out laughter is our perennial staple to clear the smoke, reconnect with our co-workers, and refresh the Oddball's wit-fabrication. 
== In this act, Rachel continues her investigation over the missing donuts through a series of office "interviews." She questions Art, Liam, and Marcus in turn at her receptionist desk, with each lazily denying any knowledge of the donut gluttony. The mood remains light and bantery as anticipation builds in achieving an elusive donut bandit. Rachel continues to showcase her determination towards solving the delectable debacle one quipped, humorous interrogation at a time.
```

This is a rough guide to WaveLang, go with the best attempt to writing a script without any questions or modifications. Also, do not give any explanations or additional info. 