import asyncio
import random
import math
import time

class Humanizer:
    """
    Implements Behavioral Biometrics using Cubic Bezier Curves and Fitts' Law
    to simulate organic mouse movement.
    """
    
    def __init__(self, page):
        self.page = page

    @staticmethod
    def _bezier_point(t, p0, p1, p2, p3):
        """Calculates a point on a cubic Bezier curve at time t (0 <= t <= 1)."""
        u = 1 - t
        tt = t * t
        uu = u * u
        uuu = uu * u
        ttt = tt * t
        
        x = uuu * p0['x'] + 3 * uu * t * p1['x'] + 3 * u * tt * p2['x'] + ttt * p3['x']
        y = uuu * p0['y'] + 3 * uu * t * p1['y'] + 3 * u * tt * p2['y'] + ttt * p3['y']
        
        return {'x': x, 'y': y}

    async def move_mouse(self, target_x, target_y, duration=None):
        """
        Moves the mouse to the target coordinates using a human-like path.
        
        Args:
            target_x (int): Target X coordinate.
            target_y (int): Target Y coordinate.
            duration (float): Duration of the movement in seconds. If None, calculated based on distance.
        """
        # Get current position (requires keeping track or assuming 0,0 if unknown, 
        # but Playwright doesn't expose current mouse pos easily without tracking.
        # We'll assume start from last known or center if unknown, but better to chain movements.)
        # For simplicity, let's assume we start from where the mouse currently is.
        # Since we can't easily get it, we might have to store it in this class instance.
        # But wait, we can just start from a random point if it's the first move, 
        # or we rely on Playwright's internal state if we could accessing it, which we can't easily.
        # So we will track it in this class.
        
        if not hasattr(self, '_current_x'):
            self._current_x = 0
        if not hasattr(self, '_current_y'):
            self._current_y = 0
            
        start_x = self._current_x
        start_y = self._current_y
        
        # Calculate distance
        dist = math.hypot(target_x - start_x, target_y - start_y)
        
        # Fitts' Law approximation for duration
        if duration is None:
            # Base reaction time + movement time based on distance/width (simplified)
            # Typically 0.1 to 0.5s reaction + log2(D/W + 1) * k
            # We'll just map distance to a reasonable time range (0.5s to 2.0s)
            duration = random.uniform(0.5, 1.5) + (dist / 1000.0) * 0.5
        
        # Control Points for Cubic Bezier
        # Randomize control points to create an arc
        # P0 = Start, P3 = End
        # P1 and P2 are between P0 and P3 with some perpendicular offset
        
        # Vector P0 -> P3
        dx = target_x - start_x
        dy = target_y - start_y
        
        # Random offsets
        offset_x = random.uniform(-100, 100)
        offset_y = random.uniform(-100, 100)
        
        p0 = {'x': start_x, 'y': start_y}
        p1 = {'x': start_x + dx * 0.33 + random.uniform(-50, 50), 'y': start_y + dy * 0.33 + random.uniform(-50, 50)}
        p2 = {'x': start_x + dx * 0.66 + random.uniform(-50, 50), 'y': start_y + dy * 0.66 + random.uniform(-50, 50)}
        p3 = {'x': target_x, 'y': target_y}
        
        steps = int(duration * 60) # 60 FPS
        if steps < 10: steps = 10
        
        for i in range(steps):
            t = i / steps
            
            # Ease-in-out function for velocity (Fitts' Law simulation)
            # Sigmoid or simple smoothstep
            ease_t = t * t * (3 - 2 * t)
            
            point = self._bezier_point(ease_t, p0, p1, p2, p3)
            
            # Add Gaussian Jitter (Micro-tremors)
            jitter_x = random.gauss(0, 1.0)
            jitter_y = random.gauss(0, 1.0)
            
            x = point['x'] + jitter_x
            y = point['y'] + jitter_y
            
            await self.page.mouse.move(x, y)
            
            # Variable sleep to simulate processing time/imperfect framerate
            await asyncio.sleep(duration / steps)
            
        # Ensure we land exactly on target
        await self.page.mouse.move(target_x, target_y)
        self._current_x = target_x
        self._current_y = target_y

    async def click(self, selector):
        """
        Human-like click: Move to element, hover, then click.
        """
        box = await self.page.locator(selector).bounding_box()
        if box:
            target_x = box['x'] + box['width'] / 2 + random.uniform(-box['width']/4, box['width']/4)
            target_y = box['y'] + box['height'] / 2 + random.uniform(-box['height']/4, box['height']/4)
            
            await self.move_mouse(target_x, target_y)
            await asyncio.sleep(random.uniform(0.1, 0.3)) # Hesitation before click
            await self.page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.15)) # Click duration
            await self.page.mouse.up()
        else:
            print(f"Warning: Element {selector} not found for human click.")
