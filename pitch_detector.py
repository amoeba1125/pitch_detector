import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame
import mido
import time
import threading
import sounddevice as sd
import numpy as np
import aubio
from collections import deque
import sys

MIN_PITCH = 30
MAX_PITCH = 90

def freq_to_note(freq):
    if freq == 0: return None
    note_num = 69 + 12 * np.log2(freq / 440.0)
    return int(round(note_num))

def note_num_to_name(note_num):
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    octave = (note_num // 12) - 1  # MIDI standard: C4=12
    note_index = note_num % 12
    return f"{note_names[note_index]}{octave}"

# ========== read MIDI notes ==========
def parse_midi_notes(midi_file):
    mid = mido.MidiFile(midi_file)

    ticks_per_beat = mid.ticks_per_beat
    tempo = 500000

    for msg in mid.tracks[0]:
        if msg.type == 'set_tempo':
            tempo = msg.tempo
            break

    notes = []
    for track in mid.tracks:
        current_tick = 0
        note_on = {}
        for msg in track:
            current_tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                note_on[msg.note] = current_tick
            elif msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                if msg.note in note_on:
                    start_tick = note_on.pop(msg.note)
                    duration_tick = current_tick - start_tick
                    start_sec = mido.tick2second(start_tick, ticks_per_beat, tempo)
                    duration_sec = mido.tick2second(duration_tick, ticks_per_beat, tempo)
                    notes.append((msg.note, start_sec, duration_sec))
    return notes

# ========== pitch detect thread ==========
mic_pitch = None    # declare global var
mic_history = deque()     # record pitch history

def start_pitch_detection():
    global mic_pitch
    samplerate = 44100
    buffer_size = 1024
    hop_size = buffer_size  # setting as same size
    pitch_o = aubio.pitch("yin", buffer_size, hop_size, samplerate)
    pitch_o.set_unit("midi")
    pitch_o.set_silence(-40)

    def callback(indata, frames, time_info, status):
        global mic_pitch
        samples = np.float32(indata[:, 0])
        pitch = pitch_o(samples)[0]
        confidence = pitch_o.get_confidence()
        if confidence > 0.8:
            mic_pitch = pitch
        else:
            mic_pitch = None

    stream = sd.InputStream(callback=callback, channels=1, samplerate=samplerate, blocksize=buffer_size)
    stream.start()

# ========== main function ==========
def run_visualizer(midi_file = ""):
    global mic_pitch
    global mic_history

    # Pygame init
    pygame.init()
    screen_width = 1000
    screen_height = 400
    screen = pygame.display.set_mode((screen_width, screen_height))
    pygame.display.set_caption("pitch detector")
    font = pygame.font.Font("C:\\Windows\\Fonts\\msjh.ttc", 18)
    text = "github.com/amoeba1125"
    text_surface = font.render(text, True, (110, 110, 110))
    text_rect = text_surface.get_rect()

    clock = pygame.time.Clock()

    # read MIDI file
    if(midi_file):
        notes = parse_midi_notes(midi_file)
        all_pitches = [note for note, _, _ in notes]
        min_pitch = min(all_pitches + [60]) - 5
        max_pitch = max(all_pitches + [72]) + 5
        pygame.mixer.init()
        pygame.mixer.music.load(midi_file)
        pygame.mixer.music.play()
    else:
        min_pitch = MIN_PITCH
        max_pitch = MAX_PITCH

    pitch_range = max_pitch - min_pitch + 1
    note_height = screen_height / pitch_range
    pixels_per_second = 100

    # start detect pitch
    threading.Thread(target=start_pitch_detection, daemon=True).start()

    start_time = time.time()
    running = True

    while running:
        frame_rate = 60
        clock.tick(frame_rate)
        current_time = time.time() - start_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # background
        screen.fill((30, 30, 30))
        text_rect.bottomright = (990, 390)
        # current position
        start_x = 200
        # scale bar
        for i in range(0, pitch_range // 2):
            y = i * note_height * 2 - 1
            pygame.draw.rect(screen, (45, 45, 45), pygame.Rect(0, y, screen_width, note_height))
        for i in range(MIN_PITCH, MAX_PITCH):
            if i % 12 == 0:
                y = screen_height - (i - min_pitch + 1) * note_height
                pygame.draw.rect(screen, (60, 45, 45), pygame.Rect(0, y, screen_width, note_height))
        y = screen_height - (60 - min_pitch + 1) * note_height
        pygame.draw.rect(screen, (90, 45, 45), pygame.Rect(0, y, screen_width, note_height))
        # current line
        pygame.draw.line(screen, (255, 255, 255), (start_x, 0), (start_x, 400), 1)

        # display MIDI notes
        if(midi_file):
            for note, start, duration in notes:
                end = start + duration
                if end >= current_time-2 and start <= current_time + screen_width / pixels_per_second:
                    x = start_x + (start - current_time) * pixels_per_second
                    y = screen_height - (note - min_pitch + 1) * note_height
                    width = duration * pixels_per_second
                    rect = pygame.Rect(x, y, width, note_height - 1)
                    pygame.draw.rect(screen, (80, 255, 80) if start >= current_time else (255, 255, 80), rect)

        # display mic pitch (current)
        if mic_pitch:
            y = screen_height - (mic_pitch - min_pitch + 0.5) * note_height
            pygame.draw.circle(screen, (255, 80, 80), (200, int(y)), 5)
            note_text = font.render(f"Mic pitch: {note_num_to_name(round(mic_pitch))}", True, (255, 255, 255))
            screen.blit(note_text, (10, 10))
        mic_history.append(y if mic_pitch else None)
        # display mic pitch (history)
        for i in range(len(mic_history) - 1):
            if mic_history[i] != None and mic_history[i+1] != None :
                pygame.draw.line(screen, (200, 70, 70),
                                (start_x - (len(mic_history) - i) * pixels_per_second / frame_rate, mic_history[i]),
                                (start_x - (len(mic_history) - i + 1) * pixels_per_second / frame_rate, mic_history[i + 1]), 
                                2)
        if len(mic_history) > 150:
            mic_history.popleft()
        # author text
        screen.blit(text_surface, text_rect)

        pygame.display.flip()

    pygame.quit()

# ==== 執行 ====
if __name__ == "__main__":
    if len(sys.argv) > 1:
        midi_file = sys.argv[1]
    else:
        midi_file = ""

    run_visualizer(midi_file)
