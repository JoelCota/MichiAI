# Training a real "Hey Michi" wake word

You don't need this to use Michi — the default `stt_phrase` engine already hears the
phrase. Do it when you want the idle CPU cost to drop to near zero, which matters if
you run her all day or on a laptop.

## Why it isn't already done

openWakeWord ships four pretrained English models (`alexa`, `hey_jarvis`,
`hey_mycroft`, `hey_rhasspy`) and none of them is "hey michi". A custom model is a
small ONNX classifier trained on synthetic speech — about 1–2 hours, mostly unattended,
and it needs CUDA, which is why it runs on Colab rather than in this project.

## Before you train: check you actually need to

Run the tuner and talk normally for a couple of minutes:

```
run.bat --tune-wake
```

It prints every phrase it hears with a match score, then tells you the highest score
that *didn't* trigger. If your false-wake rate is already zero and CPU use is fine,
stop here — you've got nothing to gain.

## The training path

1. **Open the openWakeWord training notebook in Google Colab.** The upstream one lives
   in [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) under
   `notebooks/`; several maintained community forks exist that fix version drift, e.g.
   [openwakeword-colab-2026](https://github.com/alfiedennen/openwakeword-colab-2026).
   Use a GPU runtime.

2. **Set the target phrase** to `hey michi`. The notebook uses Piper to synthesise a few
   thousand spoken variants across different voices, speeds and pitches — you don't
   record anything yourself.

3. **Let it generate negatives too.** This is the part people skip and then wonder why
   the model fires constantly. It mixes in background noise, music, and unrelated speech
   so the classifier learns what *isn't* the wake word.

4. **Train.** 75–90 minutes on a Colab GPU is typical. Output is a ~200 KB `.onnx` file.

5. **Bring it home.** Put it at `models/hey_michi.onnx` in this project, then:

   ```yaml
   wake:
     engine: openwakeword
     openwakeword:
       model: models/hey_michi.onnx
       threshold: 0.5
   ```

6. **Tune the threshold.** Start at `0.5`. Too many false wakes → raise toward `0.7`.
   Missing you → lower toward `0.35`. Set `logging.level: DEBUG` to watch the scores.

## If it goes badly

Wake-word models are sensitive to accent and recording chain. If a custom model is
worse for you than the default engine — misses you, or wakes on the TV — just switch
`wake.engine` back to `stt_phrase`. Nothing else in Michi changes; the engines are
interchangeable by design.

An in-between option: keep `stt_phrase` but raise `wake.stt_phrase.chunk_seconds` to
`3.0`. Fewer transcription passes per minute, lower CPU, slightly slower to notice you.
