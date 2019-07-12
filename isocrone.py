# Packages
import geocoder
import requests
import time
import pandas as pd
import math
import simplejson, urllib.request as urllib
import googlemaps
from gmplot import gmplot
from datetime import datetime

# Google auth
gauth='your api here'
gmaps = googlemaps.Client(key=gauth)

# Locations Dictionary
hospitals={'MUMBAI':
          ["KEM Hospital Acharya Donde Marg, Parel Mumbai 400012",
           "Dr. R N COOPER Hospital Bhaktivedanta Swami Marg, J.V.P.D. Juhu Mumbai 400056",
           "KASTURBA Hospital Saat Rasta, Sane Guruji Marg, Jacob Circle, Mumbai 400011",
           "J J Hospital Nagpada-Mumbai Central Mumbai 400008",
           "G. T. (Gokuldas Tejpal ) Hospital Nr. Police Commissioners Office, Lokmanya Tilak Marg Fort, G.P.O. Mumbai 400001",
           "Nair Hospital and Topiwala National Medical College, Dr. A. L. Nair Road, Mumbai Central Mumbai 400008",
           "Lokmanya Tilak Municipal Medical College, Dr. Babasaheb Ambedkar Marg, Sion (West), Mumbai 400022",
           "Bhabha Hospital, Waterfield Road, R.K. Patkar Marg Behind Global Cinema, Bandra (W), Mumbai 400050",
           "Tata Memorial Hospital Dr. E Borges Road, Parel, Mumbai 400012",
           "RAJWADI Hospital 7 M.G. Road, Near Somaiya College, Ghatkopar (East) Mumbai 400077"],
          "THANE":
          ["Thane Civil Hospital Near Utsal Road & Hedge Road, Opposite Police Quarter Shankar Rao Pednekar Road Tembhi Naka, Thane (West) Thane 400601",
           "Thane Mental Hospital Superintendent Bunglow, Regional Mental Hospital Near Nyan Sadhana College Thane (west) 400601",
           "Chhatrapati Shivaji Maharaj Hospital, Old Belapur Road In front of TMT Depot, Kalwa (West) Thane 400605"],
          "NAVI MUMBAI":
          ["Mathadi Hospital Trust Gyan Vikas Road, Sector 3 Kopar Khairne Navi Mumbai 400709",
           "Dr. D.Y. Patil Hospital & Research Centre Sector – 5, Nerul, Navi Mumbai 400706",
           "Sukhada Hospital No. F/3/1, F Type Market, C.B.D. Belapur Mumbai 400614"]
         }
         
# Function Definitions

# Geocoding
# adapted from https://github.com/EthanHicks1/PythonBatchGeocoder/blob/master/PythonBatchGeocoder.py
# Creates request sessions for geocoding
class GeoSessions:
    def __init__(self):
        self.Arcgis = requests.Session()
        self.Komoot = requests.Session()


# Class that is used to return 3 new sessions for each geocoding source
def create_sessions():
    return GeoSessions()


# Main geocoding function that uses the geocoding package to covert addresses into lat, longs
def geocode_address(address, s):
    g = geocoder.arcgis(address, session=s.Arcgis)
    if (g.ok == False):
        g = geocoder.komoot(address, session=s.Komoot)
    return g

def try_address(address, s, attempts_remaining, wait_time):
    g = geocode_address(address, s)
    if (g.ok == False):
        time.sleep(wait_time)
        s = create_sessions()  # It is not very likely that we can't find an address so we create new sessions and wait
        if (attempts_remaining > 0):
            try_address(address, s, attempts_remaining-1, wait_time+wait_time)
    return g
    
# Given a starting position and distance, calculate change in coordinates for a given distance
# http://www.drryanmc.com/drive-time-polygons-aka-isochrones-in-r/

def crude_distance(lat, lon, distance):
    new_lat=distance/69
    new_lon=distance/((-0.768578 - 0.00728556*lat) * (-90. + lat))
    return new_lat, new_lon

# Google query for drivetime
def gmaps_wrapper(orig_coord, dest_coord, mode="driving"):
    
    """returns the distance and time taken to travel between coodinates"""
    
    now = datetime.now()
        
    directions_result =gmaps.directions(
        orig_coord,
        dest_coord,
        mode,
        avoid="ferries",
        departure_time=now
    )
    
    duration= directions_result[0]['legs'][0]['duration']['value']
    distance= directions_result[0]['legs'][0]['distance']['value']
    
    return [duration, distance]

# Convex Polygon
def findDist(lat, lon, angle, drivetime=10, tolerance = .9, maxits = 10):
    
    # variable to hold the drive distance to the lower point
    lowerbound = 0
    distance = drivetime*.3
    
    # these next lines create the upper bound lat and lon using the crude_distance
    # function and then store this upper bound in a data frame

    upperlat, upperlon = crude_distance(lat, lon, distance)  
    
    dest_lat = lat + upperlat*math.cos(angle)
    
    dest_lon = lon + upperlon*math.sin(angle)
    
    # now we compute the drive distance to the upper lat/long
    orig_coord = lat, lon
    dest_coord = dest_lat, dest_lon
    
    try:
        max_time= gmaps_wrapper(orig_coord,dest_coord)[0]/60
    except:
        max_time= drivetime*1.1
    
    # Set iteration count to 1
    iteration =1
    
    # Set initial guess as drive time in minutes
    calc = max_time
 
    # Initialize a variable that will be used to fine tune the search boundary for time 
    ubound= distance
    
    # Loop till we reach a solution within the tolerance level
    while abs(drivetime - calc) > tolerance and iteration < maxits:
               
        #change search radius based on current drivetime versus desired time
        alpha = 1-(abs(drivetime - calc)/100)**.3
        distance = distance * alpha
        
        #use crude_distance to get lat/lon for new destiantion coordinates
        upperlat, upperlon = crude_distance(lat, lon, distance) 
        midlon = lon + upperlon * math.sin(angle)
        midlat = lat + upperlat * math.cos(angle)
        
        # now we compute the drive distance to the upper lat/long
        orig_coord = lat, lon
        dest_coord = midlat, midlon
    
        trip_detail= gmaps_wrapper(orig_coord,dest_coord)
        mid_time= trip_detail[0]/60
        mid_dist= trip_detail[1]/1000
        
        #our new best estimate is the midpoint
        calc = mid_time
    
        #increase the iteration number
        iteration = iteration + 1

        #if the required drive time is more than the current boundary then move the origin forward
        if calc - drivetime  < 0:
            
            # reset the search boundary to ensure we are not in a local maximum (such as on a hill).
            # At a distance, commute times should be quite close
            distance = ubound + distance*alpha
        
        if calc - drivetime > 0:
            
            ubound = distance
        
    return dest_coord
 
    
# Features

# Hospital geocodes
# adapted from https://github.com/EthanHicks1/PythonBatchGeocoder/blob/master/PythonBatchGeocoder.py

hospitalGeo=[]
# Variables used in the main for loop that do not need to be modified by the user
s = create_sessions()
failures = []
failed = 0
total_failed = 0
total_attempted=0
attempts_to_geocode=2
wait_time=3

for city, facilities in hospitals.items():
    for facility in facilities:
        total_attempted +=1
        g= try_address(facility, s, attempts_to_geocode, wait_time)
        if (g.ok == False):
            failures.append(facility)
            failed += 1
        else:
            hospitalGeo.append([facility, g.latlng[0], g.latlng[1]])
              
print(hospitalGeo)

print("{} failed out of {} attempted".format(total_failed,total_attempted))

# Create angles in 360 degrees. More 
num_angs = 62
angles = [0 + i/num_angs*2*math.pi for i in range(num_angs)]

# Which facility to map?
clinic = 0
facility = hospitalGeo[clinic]

serviceAreaCoords=[(findDist(facility[1],facility[2],ang)) for ang in angles]

#print(serviceAreaCoords)

# Extract latitudes and longitudes for the region in the time interval
# Some graphing tools require this format

lats=[coord[0] for coord in serviceAreaCoords]

longs=[coord[1] for coord in serviceAreaCoords]

# Place map

# First two arguments are the geographical coordinates .i.e. Latitude and Longitude and the zoom resolution.
gmap = gmplot.GoogleMapPlotter(facility[1], facility[2], 18)

# Provide the API key to gmaps 
gmap.apikey = gauth

# Plot Service Area
gmap.plot(lats, longs, 'cornflowerblue', edge_width=2)

# Mark facility
gmap.marker(facility[1], facility[2], 'cornflowerblue')

# Draw. The file will drop to your current directory
gmap.draw("my_map.html")


