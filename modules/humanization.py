"""
LUCID EMPIRE :: HUMANIZATION ENGINE
Purpose: Generates Bezier curve mouse movements.
"""
import random
import asyncio
import math


async def human_scroll(page):
    # Scroll with variable speed
    for _ in range(random.randint(3, 7)):
        await page.mouse.wheel(0, random.randint(100, 500))
        await asyncio.sleep(random.uniform(0.5, 1.5))


async def human_mouse_move(page):
    # Simple Bezier simulation
    start_x, start_y = 100, 100
    end_x, end_y = random.randint(200, 800), random.randint(200, 600)
    
    steps = 20
    for i in range(steps):
        t = i / steps
        # Linear interpolation for simplicity in this snippet, 
        # normally strictly cubic bezier
        x = start_x + (end_x - start_x) * t
        y = start_y + (end_y - start_y) * t
        
        # Add noise
        x += random.randint(-5, 5)
        y += random.randint(-5, 5)
        
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.01, 0.05))
